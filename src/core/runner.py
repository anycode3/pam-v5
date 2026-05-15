"""核心调度器：协调 netlist diff → mapper → 器件替换 → 连线重建 → DRC。

流程（无快照依赖，每次 run 完全独立）：
1. 解析原始网表和修改后网表
2. Diff 找出值变化的器件
3. 映射新值为几何参数
4. 从 GDS 提取旧引脚坐标和旧连线
5. 替换器件（重新生成 PCell）
6. 擦除旧连线 + 根据新引脚位置重新布线
7. DRC 验证（含重试循环）
8. 记录历史
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import klayout.db as db

from src.parser.kicad_netlist import KiCadNetlistParser, Component
from src.parser.target_params import TargetParam
from src.parser.netlist_diff import diff_netlists, NetlistDiffResult, DeviceDiff
from src.parser.value_parser import parse_value, value_to_device_type
from src.mapper.engine import MappingEngine, MappedGeometry
from src.validator.drc_runner import KLayoutDRCRunner
from src.validator.ref_mapper import ViolationRefMapper
from src.validator.base import ValidationResult, Severity, LVSResult
from src.validator.lvs_runner import KLayoutPureLVS
from src.routing.initial_router import InitialRouter, WireSegment, draw_wire_segments
from src.routing.wire_extractor import extract_wires_from_gds, erase_wires_from_top_cell
from src.routing.pin_extractor import extract_pin_positions, extract_pin_layers
from state.snapshot_manager import GDSBackupManager

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """版图执行结果。"""
    success: bool
    updated_cells: list[str]
    output_path: Optional[str] = None
    errors: list[str] = field(default_factory=list)
    # KLayoutExecutor 仍然使用 stretch_result，保留兼容
    stretch_result: Optional[object] = None  # StretchResult | None


@dataclass
class RunConfig:
    """运行配置。"""
    gds_path: str                  # 输入GDS
    netlist_path: str              # 原始网表
    modified_netlist_path: str     # 修改后网表
    pdk_config_path: str        # PDK 配置文件路径
    output_path: str = "output.gds"
    state_dir: str = "state"
    history_path: Optional[str] = "state/history.jsonl"
    # DRC
    drc_enabled: bool = True
    drc_rules_path: str = "config/drc_rules/simple_rf.yaml"
    drc_max_retries: int = 3
    drc_shrink_factor: float = 0.9
    # LVS
    lvs_enabled: bool = False


@dataclass
class RunResult:
    """运行结果。"""
    success: bool
    diff_result: Optional[NetlistDiffResult] = None
    mapped_geometries: list[MappedGeometry] = field(default_factory=list)
    execution_result: Optional[ExecutionResult] = None
    drc_result: Optional[ValidationResult] = None
    lvs_result: Optional[LVSResult] = None
    errors: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    drc_retries: int = 0


class Runner:
    """核心调度器（无快照依赖）。"""

    def __init__(self, config: RunConfig):
        self._config = config
        self._netlist_parser = KiCadNetlistParser()
        self._mapper = MappingEngine(config.pdk_config_path)
        self._router = InitialRouter()
        self._backup_mgr = GDSBackupManager(config.state_dir)
        if config.drc_enabled:
            self._drc_runner = KLayoutDRCRunner()
        else:
            self._drc_runner = None
        if config.lvs_enabled:
            self._lvs_runner = KLayoutPureLVS()
        else:
            self._lvs_runner = None

    def run(self) -> RunResult:
        """执行完整流程。"""
        start = time.time()
        errors = []

        # 1. 解析原始网表
        logger.info(f"解析原始网表: {self._config.netlist_path}")
        try:
            orig_components, orig_nets = self._netlist_parser.parse(
                self._config.netlist_path
            )
            logger.info(f"原始网表: {len(orig_components)} 器件, {len(orig_nets)} 网络")
        except Exception as e:
            errors.append(f"原始网表解析失败: {e}")
            return RunResult(success=False, errors=errors, duration_s=time.time() - start)

        # 2. 解析修改后网表
        logger.info(f"解析修改后网表: {self._config.modified_netlist_path}")
        try:
            mod_components, mod_nets = self._netlist_parser.parse(
                self._config.modified_netlist_path
            )
            logger.info(f"修改后网表: {len(mod_components)} 器件, {len(mod_nets)} 网络")
        except Exception as e:
            errors.append(f"修改后网表解析失败: {e}")
            return RunResult(success=False, errors=errors, duration_s=time.time() - start)

        # 3. Diff 网表
        diff_result = diff_netlists(orig_components, mod_components)
        if diff_result.errors:
            errors.extend(diff_result.errors)
            return RunResult(success=False, diff_result=diff_result, errors=errors, duration_s=time.time() - start)
        if not diff_result.has_changes:
            logger.info("网表无变化，无需更新")
            return RunResult(success=True, diff_result=diff_result, duration_s=time.time() - start)

        logger.info(f"变更器件: {[d.reference for d in diff_result.changed]}")

        # 4. 映射：新 value → 电气参数 → 几何参数
        mapped = self._map_changed_devices(diff_result.changed)
        if not mapped:
            errors.append("映射失败，无有效结果")
            return RunResult(success=False, diff_result=diff_result, errors=errors, duration_s=time.time() - start)

        # 5. 构建 ref→pcell/params 映射
        ref_to_pcell = self._build_pcell_map(orig_components, mapped)
        ref_to_params = self._build_params_map(orig_components, mapped)

        # 6. 保存 GDS 备份（回滚用）
        backup_path = self._backup_mgr.save_backup(self._config.gds_path)
        if backup_path is None:
            logger.warning("GDS 备份保存失败，无法回滚")

        # 7. 替换器件 + 重建连线
        exec_result, new_wires = self._update_layout(
            mapped, ref_to_pcell, ref_to_params,
            mod_nets, diff_result,
        )
        if not exec_result.success:
            errors.extend(exec_result.errors)

        # 8. DRC 验证
        drc_result = None
        retries = 0
        if self._drc_runner and exec_result.success:
            drc_result, retries = self._run_drc_with_retry(
                mapped, backup_path, ref_to_pcell, ref_to_params,
                mod_nets, diff_result,
            )
            if drc_result and not drc_result.passed and drc_result.has_errors():
                errors.append(
                    f"DRC未通过: {drc_result.error_count()} 错误, "
                    f"{drc_result.warning_count()} 警告 (重试{retries}次)"
                )

        # 9. LVS 验证
        lvs_result = None
        if self._lvs_runner and drc_result and drc_result.passed and exec_result.success:
            lvs_result = self._run_lvs(mod_nets, mapped)
            if lvs_result and not lvs_result.passed:
                errors.append(f"LVS未通过: {lvs_result.open_count} OPEN, {lvs_result.short_count} SHORT")
                if backup_path:
                    self._backup_mgr.restore_backup(backup_path, self._config.output_path)
                    logger.info("LVS失败，已回滚输出GDS")

        # 10. 记录历史
        self._append_history(diff_result, mapped, exec_result, drc_result, errors, retries)

        duration = time.time() - start
        logger.info(f"流程完成: {'成功' if not errors else '有错误'} ({duration:.2f}s)")

        return RunResult(
            success=len(errors) == 0,
            diff_result=diff_result,
            mapped_geometries=mapped,
            execution_result=exec_result,
            drc_result=drc_result,
            lvs_result=lvs_result,
            errors=errors,
            duration_s=duration,
            drc_retries=retries,
        )

    # ── 映射 ──

    def _map_changed_devices(
        self, changed: List[DeviceDiff]
    ) -> list[MappedGeometry]:
        """将变更器件的新 value 映射为几何参数。"""
        mapped = []
        for d in changed:
            try:
                params = parse_value(d.part_name, d.new_value)
                device_type = value_to_device_type(d.part_name)
                target = TargetParam(
                    reference=d.reference,
                    device_type=device_type,
                    params=params,
                )
                mg = self._mapper.map(target)
                mapped.append(mg)
                logger.info(f"映射: {d.reference} '{d.new_value}' → {mg.target_pcell} {mg.geometry_params}")
                if mg.warnings:
                    for w in mg.warnings:
                        logger.warning(f"约束警告 [{d.reference}]: {w}")
            except ValueError as e:
                logger.error(f"映射失败 {d.reference}: {e}")
        return mapped

    # ── 构建 ref 映射 ──

    def _build_pcell_map(
        self, components: List[Component], mapped: list[MappedGeometry]
    ) -> Dict[str, str]:
        """构建 ref→pcell_name 映射。"""
        ref_to_pcell: Dict[str, str] = {}
        # 变更器件从映射结果获取
        for mg in mapped:
            ref_to_pcell[mg.reference] = mg.target_pcell
        # 未变更器件从网表获取（part name = pcell name）
        for comp in components:
            if comp.reference not in ref_to_pcell:
                ref_to_pcell[comp.reference] = comp.name
        return ref_to_pcell

    def _build_params_map(
        self, components: List[Component], mapped: list[MappedGeometry]
    ) -> Dict[str, dict]:
        """构建 ref→params 映射。

        变更器件用新参数，未变更器件从网表 value 解析原始参数。
        """
        ref_to_params: Dict[str, dict] = {}
        # 变更器件
        for mg in mapped:
            ref_to_params[mg.reference] = mg.geometry_params
        # 未变更器件：从网表 value 解析
        for comp in components:
            if comp.reference not in ref_to_params:
                try:
                    params = parse_value(comp.name, comp.value)
                    device_type = value_to_device_type(comp.name)
                    target = TargetParam(
                        reference=comp.reference,
                        device_type=device_type,
                        params=params,
                    )
                    mg = self._mapper.map(target)
                    ref_to_params[comp.reference] = mg.geometry_params
                except ValueError:
                    logger.warning(f"无法解析未变更器件 {comp.reference} 的值: '{comp.value}'")
        return ref_to_params

    # ── 版图更新 ──

    def _update_layout(
        self,
        mapped: list[MappedGeometry],
        ref_to_pcell: Dict[str, str],
        ref_to_params: Dict[str, dict],
        nets: list,
        diff_result: NetlistDiffResult,
    ) -> Tuple[ExecutionResult, Dict[str, List[WireSegment]]]:
        """替换器件 + 重建连线。

        Returns:
            (ExecutionResult, {net_name: [WireSegment]}) 新连线数据
        """
        from pcells.registry import get_pcell

        gds_path = Path(self._config.gds_path)
        output_path = Path(self._config.output_path)

        # 复制输入GDS到输出
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(gds_path, output_path)

        # 加载版图
        layout = db.Layout()
        layout.read(str(output_path))
        top_cell = layout.top_cell()

        if top_cell is None:
            return ExecutionResult(
                success=False, updated_cells=[], errors=["无法读取 top cell"]
            ), {}

        # ── 步骤1: 从 GDS 提取旧连线 ──
        old_wires = extract_wires_from_gds(layout, top_cell, nets)

        # ── 步骤2: 替换器件 ──
        updated_cells = []
        all_errors = []

        for mg in mapped:
            try:
                target_cell = self._find_cell_by_reference(layout, mg.reference)
                if target_cell is None:
                    all_errors.append(f"未找到器件: {mg.reference}")
                    continue

                pcell = get_pcell(mg.target_pcell)
                valid, param_errors = pcell.validate_params(mg.geometry_params, mg.constraints)
                if not valid:
                    for e in param_errors:
                        err_msg = f"参数校验失败 [{mg.reference}]: {e}"
                        all_errors.append(err_msg)
                        logger.error(err_msg)
                    continue  # 参数无效，跳过该器件的更新

                target_cell.clear()
                pcell.generate(target_cell, mg.geometry_params)
                updated_cells.append(mg.reference)
                logger.info(f"已更新: {mg.reference} ({mg.target_pcell}) → {mg.geometry_params}")

            except Exception as e:
                all_errors.append(f"更新失败 {mg.reference}: {e}")
                logger.error(f"更新失败: {mg.reference}", exc_info=True)

        # ── 步骤3: 擦除受影响网络的旧连线 ──
        changed_refs = [d.reference for d in diff_result.changed]
        affected_nets = self._find_affected_nets(nets, changed_refs)
        if affected_nets and old_wires:
            erase_wires_from_top_cell(layout, top_cell, affected_nets, old_wires)

        # ── 步骤4: 重新布线 ──
        new_wires = self._router.route_affected_nets(
            layout=layout,
            top_cell=top_cell,
            nets=nets,
            changed_refs=changed_refs,
            ref_to_pcell=ref_to_pcell,
            ref_to_params=ref_to_params,
            old_wires=None,  # 已经手动擦除了，不需要 router 再擦
        )

        # 绘制新连线
        for net_name, wires in new_wires.items():
            draw_wire_segments(top_cell, layout, wires)
            logger.info(f"已绘制连线: {net_name} ({len(wires)} 段)")

        # 保存
        layout.write(str(output_path))
        logger.info(f"GDS已保存: {output_path}")

        return ExecutionResult(
            success=len(all_errors) == 0,
            updated_cells=updated_cells,
            output_path=str(output_path),
            errors=all_errors,
        ), new_wires

    def _find_affected_nets(
        self, nets: list, changed_refs: List[str]
    ) -> List[str]:
        """找出涉及变更器件的网络名列表。"""
        changed_set = set(changed_refs)
        affected = []
        for net in nets:
            for ref, _ in net.nodes:
                if ref in changed_set:
                    affected.append(net.name)
                    break
        return affected

    # ── DRC ──

    def _run_drc_with_retry(
        self,
        mapped: list[MappedGeometry],
        backup_path: Optional[Path],
        ref_to_pcell: Dict[str, str],
        ref_to_params: Dict[str, dict],
        nets: list,
        diff_result: NetlistDiffResult,
    ) -> Tuple[Optional[ValidationResult], int]:
        """DRC 验证 + 重试循环。"""
        max_retries = self._config.drc_max_retries if self._drc_runner else 0
        current_mapped = mapped

        for attempt in range(max_retries + 1):
            drc_result = self._drc_runner.run(
                gds_path=self._config.output_path,
                rules_path=self._config.drc_rules_path,
            )

            if drc_result.passed:
                logger.info(f"DRC通过 (attempt {attempt + 1})")
                return drc_result, attempt

            # DRC 失败
            layout = db.Layout()
            layout.read(self._config.output_path)
            ref_mapper = ViolationRefMapper.from_layout(layout)
            drc_result.violations = ref_mapper.map_violations(drc_result.violations)

            logger.warning(f"DRC失败 (attempt {attempt + 1}/{max_retries + 1}): {drc_result.violation_count} 违例")

            if attempt < max_retries:
                if backup_path:
                    self._backup_mgr.restore_backup(backup_path, self._config.output_path)
                    logger.info("已回滚到备份")

                adjusted = self._adjust_for_drc(current_mapped, drc_result)
                if adjusted == current_mapped:
                    logger.error("无法自动修正DRC违例，停止重试")
                    return drc_result, attempt + 1
                current_mapped = adjusted

                retry_exec, _ = self._update_layout(
                    current_mapped, ref_to_pcell, ref_to_params,
                    nets, diff_result,
                )
                if not retry_exec.success:
                    logger.error(f"重试布局更新失败: {retry_exec.errors}")
                    return drc_result, attempt + 1
            else:
                if backup_path:
                    self._backup_mgr.restore_backup(backup_path, self._config.output_path)
                    logger.info("重试次数用尽，已回滚")

        return drc_result, max_retries

    def _adjust_for_drc(
        self, mapped: list[MappedGeometry], drc_result: ValidationResult
    ) -> list[MappedGeometry]:
        """根据DRC违例缩小几何参数。"""
        violated_refs = set()
        for v in drc_result.violations:
            if v.severity == Severity.ERROR and v.related_refs:
                violated_refs.update(v.related_refs)

        if not violated_refs:
            return mapped

        factor = self._config.drc_shrink_factor
        adjusted = []
        any_changed = False

        for mg in mapped:
            if mg.reference in violated_refs:
                new_params = {}
                for k, v in mg.geometry_params.items():
                    if isinstance(v, (int, float)) and k != "angle":
                        new_val = v * factor
                        new_params[k] = round(new_val, 2)
                        if new_val != v:
                            any_changed = True
                    else:
                        new_params[k] = v
                adjusted.append(MappedGeometry(
                    reference=mg.reference,
                    target_pcell=mg.target_pcell,
                    geometry_params=new_params,
                    warnings=mg.warnings,
                ))
            else:
                adjusted.append(mg)

        return adjusted if any_changed else mapped

    # ── LVS ──

    def _run_lvs(self, nets: list, mapped: list[MappedGeometry]):
        """执行LVS验证。"""
        schematic_nets: Dict[str, List[str]] = {}
        for net in nets:
            if net.name:
                schematic_nets[net.name] = [f"{ref}.{pin}" for ref, pin in net.nodes]

        layout = db.Layout()
        layout.read(self._config.output_path)
        top_cell = layout.top_cell()
        if top_cell is None:
            return None

        # 复用 pin_extractor 提取引脚坐标
        ref_pin_positions = extract_pin_positions(layout, top_cell)

        pin_positions: Dict[str, Tuple[float, float]] = {}
        for ref, pins in ref_pin_positions.items():
            for pin_name, (x, y) in pins.items():
                pin_positions[f"{ref}.{pin_name}"] = (x, y)

        if not pin_positions:
            logger.warning("LVS: 未找到PIN markers")
            return None

        return self._lvs_runner.run(
            gds_path=self._config.output_path,
            schematic_nets=schematic_nets,
            pin_positions=pin_positions,
        )

    # ── 辅助方法 ──

    def _find_cell_by_reference(
        self, layout: db.Layout, reference: str
    ) -> Optional[db.Cell]:
        """按 reference 定位 Cell。

        Cell 命名格式为 ref_pcell_name（如 C1_CAP_MIM）。
        用精确匹配避免 C1 错误匹配 C10。
        """
        top_cell = layout.top_cell()
        if top_cell is None:
            return None
        for inst in top_cell.each_inst():
            cell = inst.cell
            if cell.name == reference:
                return cell
            if cell.name.startswith(f"{reference}_"):
                suffix = cell.name[len(reference) + 1:]
                if suffix and not suffix[0].isdigit():
                    return cell
        return None

    def _append_history(
        self,
        diff_result: NetlistDiffResult,
        mapped: list[MappedGeometry],
        exec_result: ExecutionResult,
        drc_result: Optional[ValidationResult],
        errors: list[str],
        drc_retries: int,
    ) -> None:
        """追加操作历史。"""
        if not self._config.history_path:
            return
        history_path = Path(self._config.history_path)
        history_path.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "action": "layout_update",
            "changes": [
                {"reference": d.reference, "old_value": d.old_value, "new_value": d.new_value}
                for d in diff_result.changed
            ],
            "mapped": [
                {"reference": mg.reference, "pcell": mg.target_pcell, "geometry": mg.geometry_params}
                for mg in mapped
            ],
            "result": "success" if not errors else "partial_failure",
            "errors": errors,
            "updated_cells": exec_result.updated_cells if exec_result else [],
            "drc": {
                "enabled": self._config.drc_enabled,
                "passed": drc_result.passed if drc_result else None,
                "violations": drc_result.violation_count if drc_result else 0,
                "retries": drc_retries,
            } if drc_result else None,
        }

        with open(history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
