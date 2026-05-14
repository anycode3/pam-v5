"""核心调度器：协调 parser → mapper → executor → DRC验证 流程。"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import klayout.db as db

from src.parser.kicad_netlist import KiCadNetlistParser
from src.parser.target_params import TargetParamsParser
from src.mapper.engine import MappingEngine
from src.executor.klayout_executor import KLayoutExecutor, ExecutionResult
from src.mapper.engine import MappedGeometry
from src.validator.drc_runner import KLayoutDRCRunner
from src.validator.ref_mapper import ViolationRefMapper
from src.validator.base import ValidationResult, Severity, LVSResult
from src.validator.lvs_runner import KLayoutPureLVS
from src.state.snapshot_manager import SnapshotManager, ParamsSnapshot, DeviceSnapshot, PinSnapshot
from src.routing.types import PinState

logger = logging.getLogger(__name__)


@dataclass
class RunConfig:
    """运行配置。"""
    gds_path: str                # 输入GDS
    netlist_path: str            # KiCad网表
    target_params_path: str      # 目标参数JSON
    mapping_rules_path: str      # 映射规则YAML
    output_path: str = "output.gds"  # 输出GDS
    state_dir: str = "state"         # 状态目录（存快照和参数快照）
    snapshot_dir: Optional[str] = None  # GDS快照目录（默认state_dir/snapshots）
    history_path: Optional[str] = "state/history.jsonl"
    stretch_threshold_dbu: float = 10000
    # DRC
    drc_enabled: bool = True
    drc_rules_path: str = "config/drc_rules/simple_rf.yaml"
    drc_max_retries: int = 3
    drc_shrink_factor: float = 0.9  # DRC重试时参数缩小系数
    # LVS（二期）
    lvs_enabled: bool = False


@dataclass
class RunResult:
    """运行结果。"""
    success: bool
    mapped_geometries: list[MappedGeometry] = field(default_factory=list)
    execution_result: Optional[ExecutionResult] = None
    drc_result: Optional[ValidationResult] = None
    lvs_result: Optional[LVSResult] = None
    errors: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    drc_retries: int = 0


class Runner:
    """核心调度器，含DRC验证与重试循环。"""

    def __init__(self, config: RunConfig):
        self._config = config
        self._netlist_parser = KiCadNetlistParser()
        self._target_parser = TargetParamsParser()
        self._mapper = MappingEngine(config.mapping_rules_path)
        self._executor = KLayoutExecutor(
            stretch_threshold_um=config.stretch_threshold_dbu * 0.001,  # dbu→um
        )
        if config.drc_enabled:
            self._drc_runner = KLayoutDRCRunner()
        else:
            self._drc_runner = None
        if config.lvs_enabled:
            self._lvs_runner = KLayoutPureLVS()
        else:
            self._lvs_runner = None
        self._nets: list = []  # 最近一次解析的网络列表
        # 状态管理器
        self._snapshot_mgr = SnapshotManager(config.state_dir)
        self._params_snapshot_path = Path(config.state_dir) / "params_snapshot.json"

    def run(self) -> RunResult:
        """执行完整流程：解析→映射→执行→DRC验证（含重试循环）。"""
        start = time.time()
        errors = []

        # 1. 解析网表
        logger.info(f"解析网表: {self._config.netlist_path}")
        try:
            components, self._nets = self._netlist_parser.parse(
                self._config.netlist_path
            )
            logger.info(f"网表解析完成: {len(components)} 器件, {len(self._nets)} 网络")
        except Exception as e:
            errors.append(f"网表解析失败: {e}")
            return RunResult(success=False, errors=errors, duration_s=time.time()-start)

        # 2. 解析目标参数
        logger.info(f"解析目标参数: {self._config.target_params_path}")
        try:
            targets = self._target_parser.parse(self._config.target_params_path)
            logger.info(f"目标参数: {len(targets)} 个器件待更新")
        except Exception as e:
            errors.append(f"目标参数解析失败: {e}")
            return RunResult(success=False, errors=errors, duration_s=time.time()-start)

        # 3. 映射
        logger.info("执行电气→几何映射...")
        mapped = []
        for t in targets:
            try:
                mg = self._mapper.map(t)
                mapped.append(mg)
                if mg.warnings:
                    for w in mg.warnings:
                        logger.warning(f"约束警告 [{mg.reference}]: {w}")
                logger.info(f"映射: {mg.reference} → {mg.target_pcell} {mg.geometry_params}")
            except ValueError as e:
                errors.append(str(e))
                logger.error(f"映射失败: {e}")

        if not mapped:
            errors.append("无有效映射结果")
            return RunResult(success=False, errors=errors, duration_s=time.time()-start)

        # 4. 加载旧参数快照（为StretchRouter提供old_pin_states）
        old_params_snapshot = self._snapshot_mgr.load_params_state(self._params_snapshot_path)
        old_pin_states = self._extract_old_pin_states(old_params_snapshot, mapped)

        # 5. 保存GDS快照（回滚用）
        snapshot_path = self._save_snapshot()

        # 6. 执行 + DRC重试循环
        exec_result, drc_result, retries = self._execute_with_drc_loop(
            mapped, snapshot_path, old_pin_states
        )

        if not exec_result.success:
            errors.extend(exec_result.errors)

        # 7. DRC结果处理
        if drc_result and not drc_result.passed:
            if drc_result.has_errors():
                errors.append(
                    f"DRC未通过: {drc_result.error_count()} 错误, "
                    f"{drc_result.warning_count()} 警告 "
                    f"(重试{retries}次后仍失败)"
                )

        # 8. LVS验证（DRC成功后执行，失败则回滚不重试）
        lvs_result = None
        if self._lvs_runner and drc_result and drc_result.passed and exec_result.success:
            lvs_result = self._run_lvs(mapped, snapshot_path)
            if lvs_result and not lvs_result.passed:
                errors.append(
                    f"LVS未通过: {lvs_result.open_count} OPEN, "
                    f"{lvs_result.short_count} SHORT"
                )
                # 回滚输出GDS到快照
                if snapshot_path and snapshot_path.exists():
                    shutil.copy2(snapshot_path, self._config.output_path)
                    logger.info("LVS失败，已回滚输出GDS")

        # 9. DRC+LVS都成功时更新参数快照
        if drc_result and drc_result.passed and exec_result.success and (lvs_result is None or lvs_result.passed):
            self._save_params_snapshot(mapped, exec_result)

        # 10. 记录历史
        self._append_history(mapped, exec_result, drc_result, errors, retries)

        duration = time.time() - start
        logger.info(f"流程完成: {'成功' if not errors else '有错误'} ({duration:.2f}s)")

        return RunResult(
            success=len(errors) == 0,
            mapped_geometries=mapped,
            execution_result=exec_result,
            drc_result=drc_result,
            lvs_result=lvs_result,
            errors=errors,
            duration_s=duration,
            drc_retries=retries,
        )

    def _execute_with_drc_loop(
        self,
        mapped: list[MappedGeometry],
        snapshot_path: Optional[Path],
        old_pin_states: Optional[Dict[str, PinState]] = None,
    ) -> tuple[ExecutionResult, Optional[ValidationResult], int]:
        """执行版图更新 + DRC验证循环。

        Returns:
            (exec_result, drc_result, retry_count)
        """
        max_retries = self._config.drc_max_retries if self._drc_runner else 0
        current_mapped = mapped

        # 构建netlist_nets: {net_name: [(ref, pin_name), ...]}
        netlist_nets: Dict[str, List] = {}
        for net in self._nets:
            netlist_nets[net.name] = net.nodes

        for attempt in range(max_retries + 1):
            # 执行版图更新
            exec_result = self._executor.execute(
                gds_path=self._config.gds_path,
                mapped_geometries=current_mapped,
                output_path=self._config.output_path,
                snapshot_dir=None,  # 快照由runner管理
                netlist_nets=netlist_nets,
                old_pin_states=old_pin_states,
            )

            if not exec_result.success:
                return exec_result, None, attempt

            # DRC验证
            if self._drc_runner is None:
                return exec_result, None, 0

            drc_result = self._drc_runner.run(
                gds_path=self._config.output_path,
                rules_path=self._config.drc_rules_path,
            )

            if drc_result.passed:
                logger.info(f"DRC通过 (attempt {attempt + 1})")
                return exec_result, drc_result, attempt

            # DRC失败
            # 关联违例到器件
            layout = db.Layout()
            layout.read(self._config.output_path)
            ref_mapper = ViolationRefMapper.from_layout(layout)
            drc_result.violations = ref_mapper.map_violations(drc_result.violations)

            logger.warning(
                f"DRC失败 (attempt {attempt + 1}/{max_retries + 1}): "
                f"{drc_result.violation_count} 违例"
            )
            for v in drc_result.violations:
                refs = v.related_refs or []
                logger.warning(
                    f"  {v.rule_name}: {v.description} @ ({v.x:.1f},{v.y:.1f}) "
                    f"refs={refs}"
                )

            # 尝试重试
            if attempt < max_retries:
                # 回滚到修改前
                if snapshot_path and snapshot_path.exists():
                    shutil.copy2(snapshot_path, self._config.gds_path)
                    logger.info(f"已回滚到快照: {snapshot_path}")

                # 修正参数（缩小违例器件的几何参数）
                adjusted = self._adjust_for_drc(current_mapped, drc_result)
                if adjusted == current_mapped:
                    logger.error("无法自动修正DRC违例，停止重试")
                    return exec_result, drc_result, attempt + 1
                current_mapped = adjusted
            else:
                # 重试次数用尽，回滚
                if snapshot_path and snapshot_path.exists():
                    shutil.copy2(snapshot_path, self._config.output_path)
                    logger.info("重试次数用尽，已回滚输出GDS")

        return exec_result, drc_result, max_retries

    def _adjust_for_drc(
        self,
        mapped: list[MappedGeometry],
        drc_result: ValidationResult,
    ) -> list[MappedGeometry]:
        """根据DRC违例调整几何参数。

        简化策略：对违例关联的器件，将几何参数按系数缩小。
        """
        # 找出有违例的器件
        violated_refs = set()
        for v in drc_result.violations:
            if v.severity == Severity.ERROR and v.related_refs:
                violated_refs.update(v.related_refs)

        if not violated_refs:
            return mapped  # 无法确定哪个器件有问题

        # 缩小参数
        factor = self._config.drc_shrink_factor
        adjusted = []
        any_changed = False

        for mg in mapped:
            if mg.reference in violated_refs:
                new_params = {}
                for k, v in mg.geometry_params.items():
                    if isinstance(v, (int, float)) and k not in ("angle",):
                        new_val = v * factor
                        new_params[k] = round(new_val, 2)
                        if new_val != v:
                            any_changed = True
                    else:
                        new_params[k] = v
                logger.info(
                    f"DRC修正 {mg.reference}: {mg.geometry_params} → {new_params}"
                )
                adjusted.append(MappedGeometry(
                    reference=mg.reference,
                    target_pcell=mg.target_pcell,
                    geometry_params=new_params,
                    warnings=mg.warnings,
                ))
            else:
                adjusted.append(mg)

        return adjusted if any_changed else mapped

    def _save_snapshot(self) -> Optional[Path]:
        """保存输入GDS快照。"""
        snapshot_dir = self._config.snapshot_dir or str(Path(self._config.state_dir) / "snapshots")
        snapshot_dir = Path(snapshot_dir)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        snapshot_path = snapshot_dir / f"pre_update_{ts}.gds"

        src = Path(self._config.gds_path)
        if src.exists():
            shutil.copy2(src, snapshot_path)
            logger.info(f"快照已保存: {snapshot_path}")
            return snapshot_path
        return None

    def _extract_old_pin_states(
        self,
        params_snapshot: Optional[ParamsSnapshot],
        mapped: list[MappedGeometry],
    ) -> Dict[str, PinState]:
        """从参数快照提取旧引脚状态。

        Args:
            params_snapshot: 上次成功的参数快照
            mapped: 当前待更新的器件映射

        Returns:
            {ref.pin_name: PinState}
        """
        if params_snapshot is None:
            return {}

        old_pins: Dict[str, PinState] = {}
        for mg in mapped:
            if mg.reference not in params_snapshot.devices:
                continue
            dev_snap = params_snapshot.devices[mg.reference]
            for pin_name, pin_snap in dev_snap.pins.items():
                key = f"{mg.reference}.{pin_name}"
                old_pins[key] = PinState(
                    name=pin_name,
                    ref=mg.reference,
                    x=pin_snap.x,
                    y=pin_snap.y,
                )
        return old_pins

    def _save_params_snapshot(
        self,
        mapped: list[MappedGeometry],
        exec_result: ExecutionResult,
    ) -> None:
        """保存当前参数快照（DRC通过后调用）。"""
        from pcells.registry import get_pcell

        devices: Dict[str, DeviceSnapshot] = {}
        for mg in mapped:
            try:
                pcell = get_pcell(mg.target_pcell)
                pin_positions = pcell.get_pin_positions(mg.geometry_params)
                pins = {
                    pin_name: PinSnapshot(name=pin_name, x=pos.x, y=pos.y)
                    for pin_name, pos in pin_positions.items()
                }
                devices[mg.reference] = DeviceSnapshot(
                    ref=mg.reference,
                    pcell_type=mg.target_pcell,
                    params=mg.geometry_params,
                    pins=pins,
                )
            except Exception as e:
                logger.warning(f"快照保存时无法获取{mg.reference}引脚: {e}")

        snapshot = ParamsSnapshot(
            gds_path=self._config.output_path,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            devices=devices,
        )
        self._snapshot_mgr.save_params_state(self._params_snapshot_path, snapshot)

    def _run_lvs(
        self,
        mapped: list[MappedGeometry],
        snapshot_path: Optional[Path],
    ):
        """执行LVS验证。

        Returns:
            LVSResult if lvs_enabled else None
        """
        from pcells.registry import get_pcell

        # 构建 schematic_nets: {net_name: [ref.pin_name, ...]}
        schematic_nets: Dict[str, List[str]] = {}
        for net in self._nets:
            if net.name:
                schematic_nets[net.name] = [
                    f"{ref}.{pin}" for ref, pin in net.nodes
                ]

        # 构建 pin_positions: {ref.pin_name: (x_um, y_um)}
        # 遍历top cell实例，从cell名+marker文本构造ref.pin_name
        pin_positions: Dict[str, Tuple[float, float]] = {}

        layout = db.Layout()
        layout.read(self._config.output_path)
        top_cell = layout.top_cell()
        if top_cell is None:
            logger.warning("LVS: 无法读取top cell")
            return None

        marker_layer = layout.layer(db.LayerInfo(255, 0))
        if marker_layer < 0:
            logger.warning("LVS: 未找到PIN marker层(255/0)")
            return None

        # 建立 ref → (cell, instance_transform) 的映射
        ref_to_cell: Dict[str, db.Cell] = {}
        ref_to_trans: Dict[str, db.Trans] = {}
        for mg in mapped:
            for inst in top_cell.each_inst():
                cell = inst.cell
                if cell.name.startswith(f"{mg.reference}_") or cell.name == mg.reference:
                    ref_to_cell[mg.reference] = cell
                    ref_to_trans[mg.reference] = inst.trans
                    break

        # 遍历子cell的PIN marker，将本地坐标变换为全局坐标
        for ref, cell in ref_to_cell.items():
            inst_trans = ref_to_trans[ref]
            for shape in cell.shapes(marker_layer).each():
                if shape.is_text():
                    text_obj = shape.text
                    pin_label = text_obj.string
                    # 本地坐标(dbu) → 全局坐标(dbu)
                    local_pt = db.Point(text_obj.x, text_obj.y)
                    global_pt = inst_trans * local_pt
                    # dbu → um
                    px_um = global_pt.x * layout.dbu
                    py_um = global_pt.y * layout.dbu
                    pin_key = f"{ref}.{pin_label}"
                    pin_positions[pin_key] = (px_um, py_um)

        if not pin_positions:
            logger.warning("LVS: 未找到任何PIN markers")
            return None

        logger.info(f"LVS: {len(schematic_nets)} nets, {len(pin_positions)} pins")

        # 执行LVS
        lvs_result = self._lvs_runner.run(
            gds_path=self._config.output_path,
            schematic_nets=schematic_nets,
            pin_positions=pin_positions,
        )

        if lvs_result.passed:
            logger.info("LVS通过")
        else:
            for v in lvs_result.violations:
                logger.warning(f"LVS违例: {v.violation_type} {v.net_name}: {v.description}")

        return lvs_result

    def _append_history(
        self,
        mapped: list[MappedGeometry],
        exec_result: ExecutionResult,
        drc_result: Optional[ValidationResult],
        errors: list[str],
        drc_retries: int,
    ) -> None:
        """追加操作历史到history.jsonl。"""
        if not self._config.history_path:
            return

        history_path = Path(self._config.history_path)
        history_path.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "action": "layout_update",
            "params": [
                {
                    "reference": mg.reference,
                    "pcell": mg.target_pcell,
                    "geometry": mg.geometry_params,
                    "warnings": mg.warnings,
                }
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
