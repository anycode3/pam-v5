"""KLayout执行器：PCell定位、参数更新、连线维护、GDS保存。

使用 klayout.db headless API，通过PCell registry调用器件实现。
支持WireFinder连线发现+StretchRouter实际拉伸。
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import klayout.db as db

from src.mapper.engine import MappedGeometry
from src.pcells.base import BasePCell, PinPosition
from src.pcells.registry import get_pcell
from src.routing.base import RoutingStrategy, StretchRouter
from src.routing.types import PinState, Connection, StretchResult
from src.routing.wire_finder import WireFinder

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """执行结果。"""
    success: bool
    updated_cells: list[str]     # 成功更新的PCell实例reference
    stretch_result: Optional[StretchResult] = None
    output_path: Optional[str] = None
    errors: list[str] = field(default_factory=list)


class KLayoutExecutor:
    """KLayout版图执行器。

    负责：加载GDS → 记录旧引脚位置 → 定位PCell → 生成新几何 →
         连线发现 → 实际拉伸 → 保存GDS。
    """

    def __init__(
        self,
        routing_strategy: Optional[RoutingStrategy] = None,
        stretch_threshold_um: float = 100.0,
        wire_finder: Optional[WireFinder] = None,
    ):
        self._routing = routing_strategy or StretchRouter()
        self._stretch_threshold_um = stretch_threshold_um
        self._wire_finder = wire_finder or WireFinder()

    def execute(
        self,
        gds_path: str | Path,
        mapped_geometries: list[MappedGeometry],
        output_path: str | Path,
        snapshot_dir: Optional[str | Path] = None,
        netlist_nets: Optional[Dict[str, List]] = None,
        old_pin_states: Optional[Dict[str, PinState]] = None,
    ) -> ExecutionResult:
        """执行版图更新。

        Args:
            gds_path: 输入GDS文件路径
            mapped_geometries: 映射后的几何参数列表
            output_path: 输出GDS文件路径
            snapshot_dir: 快照目录（回滚用），None则不备份
            netlist_nets: 网表连接信息 {net_name: [(ref, pin_name), ...]}
                         提供后启用连线发现和实际拉伸
            old_pin_states: 上次成功执行的引脚状态 {ref.pin_name: PinState}
                          来源：StateManager参数快照
        """
        gds_path = Path(gds_path)
        output_path = Path(output_path)

        # 快照备份
        if snapshot_dir:
            snapshot_dir = Path(snapshot_dir)
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            import time
            ts = time.strftime("%Y%m%d_%H%M%S")
            snapshot_file = snapshot_dir / f"snapshot_{ts}.gds"
            shutil.copy2(gds_path, snapshot_file)
            logger.info(f"快照已保存: {snapshot_file}")

        # 加载版图
        layout = db.Layout()
        layout.read(str(gds_path))

        updated_cells = []
        all_errors = []
        last_stretch_result = None

        # ── 第1步：收集ref→pcell映射 ──
        ref_to_pcell: Dict[str, str] = {}

        for mg in mapped_geometries:
            try:
                target_cell = self._find_cell_by_reference(layout, mg.reference)
                if target_cell is None:
                    continue
                ref_to_pcell[mg.reference] = mg.target_pcell
            except ValueError:
                pass

        # ── 第2步：执行PCell更新 ──
        for mg in mapped_geometries:
            try:
                target_cell = self._find_cell_by_reference(layout, mg.reference)
                if target_cell is None:
                    all_errors.append(f"未找到PCell实例: reference={mg.reference}")
                    continue

                pcell = get_pcell(mg.target_pcell)

                # 参数校验
                valid, param_errors = pcell.validate_params(mg.geometry_params)
                if not valid:
                    for e in param_errors:
                        logger.warning(f"参数校验 [{mg.reference}]: {e}")

                # 通过PCell生成新几何
                target_cell.clear()
                pcell.generate(target_cell, mg.geometry_params)
                updated_cells.append(mg.reference)
                logger.info(f"已更新: {mg.reference} ({mg.target_pcell}) → {mg.geometry_params}")

            except ValueError as e:
                all_errors.append(f"PCell查找失败 {mg.reference}: {e}")
            except Exception as e:
                all_errors.append(f"更新失败 {mg.reference}: {e}")
                logger.error(f"更新失败: {mg.reference}", exc_info=True)

        # ── 第3步：连线发现和实际拉伸 ──
        if netlist_nets and updated_cells:
            stretch_result = self._do_stretch(
                layout, mapped_geometries, netlist_nets, ref_to_pcell,
                old_pin_states=old_pin_states or {},
            )
            last_stretch_result = stretch_result
            logger.info(
                f"连线维护: 拉伸{len(stretch_result.stretched)}条, "
                f"断线{len(stretch_result.broken)}条"
            )

        # ── 第4步：保存 ──
        output_path.parent.mkdir(parents=True, exist_ok=True)
        layout.write(str(output_path))
        logger.info(f"GDS已保存: {output_path}")

        return ExecutionResult(
            success=len(all_errors) == 0,
            updated_cells=updated_cells,
            stretch_result=last_stretch_result,
            output_path=str(output_path),
            errors=all_errors,
        )

    def _do_stretch(
        self,
        layout: db.Layout,
        mapped_geometries: list[MappedGeometry],
        netlist_nets: Dict[str, List],
        ref_to_pcell: Dict[str, str],
        old_pin_states: Optional[Dict[str, PinState]] = None,
    ) -> StretchResult:
        """执行连线发现和拉伸。

        Args:
            layout: KLayout Layout对象
            mapped_geometries: 当前映射结果
            netlist_nets: 网表连接信息
            ref_to_pcell: {ref: pcell_name}
            old_pin_states: 上次成功执行的引脚状态（来自StateManager快照）
        """
        top_cell = layout.top_cell()
        if top_cell is None:
            return StretchResult()

        old_pins = old_pin_states or {}

        # 构建 ref→params 映射（新参数）
        ref_to_new_params = {mg.reference: mg.geometry_params for mg in mapped_geometries}

        # 用WireFinder发现连线
        connections = self._wire_finder.find_connections(
            layout=layout,
            top_cell=top_cell,
            netlist_nets=netlist_nets,
            ref_to_pcell=ref_to_pcell,
            ref_to_params=ref_to_new_params,
        )

        # 计算新引脚位置
        new_pins: Dict[str, PinState] = {}

        for mg in mapped_geometries:
            try:
                pcell = get_pcell(mg.target_pcell)
                new_positions = pcell.get_pin_positions(mg.geometry_params)

                for pin_name, pos in new_positions.items():
                    key = f"{mg.reference}.{pin_name}"
                    new_pins[key] = PinState(
                        name=pin_name, ref=mg.reference, x=pos.x, y=pos.y
                    )
            except Exception:
                pass

        # 无旧位置时跳过拉伸
        if not old_pins:
            logger.info("无旧引脚位置信息，跳过连线拉伸")
            return StretchResult(
                stretched=[],
                broken=[],
                total=len(connections),
            )

        # 执行拉伸
        stretch_router = self._routing
        if isinstance(stretch_router, StretchRouter):
            return stretch_router.stretch_connections(
                layout=layout,
                cell=top_cell,
                connections=connections,
                old_pins=old_pins,
                new_pins=new_pins,
                threshold_um=self._stretch_threshold_um,
            )

        return StretchResult(total=len(connections))

    def _find_cell_by_reference(
        self, layout: db.Layout, reference: str
    ) -> Optional[db.Cell]:
        """按reference定位Cell。"""
        top_cell = layout.top_cell()
        if top_cell is None:
            return None

        # 优先精确匹配和前缀匹配（reference="TL1" 匹配 "TL1_TL_MICROSTRIP"）
        for inst in top_cell.each_inst():
            cell = inst.cell
            if cell.name == reference or cell.name.startswith(f"{reference}_"):
                return cell

        return None
