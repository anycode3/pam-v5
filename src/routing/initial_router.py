"""初始布线器：根据网表连接关系，在器件引脚之间绘制连线。

用于：
1. 首次生成版图时，在器件间画初始走线
2. 器件参数变更后，重建受影响的连线

策略：
- 同层同线引脚：直连
- 不同层或不对齐：L型折线（先画到拐点，再到目标）
- 层选择：使用引脚A的层（信号源端）
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import klayout.db as db

from .types import PinState, WireSegment
from pcells.registry import get_pcell

logger = logging.getLogger(__name__)

# 默认连线参数
DEFAULT_WIRE_WIDTH = 10.0  # um
DEFAULT_WIRE_LAYER = (6, 0)  # METAL_UNDER，通用走线层
# 共线判断公差：水平/垂直误差小于 wire_width/2 时视为共线
COLINEAR_TOLERANCE = DEFAULT_WIRE_WIDTH / 2.0  # 5.0 um


def route_connection(
    pin_a: PinState,
    pin_b: PinState,
    pin_a_layer: Tuple[int, int] = DEFAULT_WIRE_LAYER,
    pin_b_layer: Tuple[int, int] = DEFAULT_WIRE_LAYER,
    wire_width: float = DEFAULT_WIRE_WIDTH,
) -> List[WireSegment]:
    """在两个引脚之间规划连线。

    Args:
        pin_a: 引脚A
        pin_b: 引脚B
        pin_a_layer: 引脚A所在层
        pin_b_layer: 引脚B所在层
        wire_width: 走线宽度 (um)

    Returns:
        WireSegment 列表
    """
    ax, ay = pin_a.x, pin_a.y
    bx, by = pin_b.x, pin_b.y

    # 选择走线层：优先使用引脚A的层
    wire_layer = pin_a_layer

    dx = abs(bx - ax)
    dy = abs(by - ay)

    if dx < COLINEAR_TOLERANCE or dy < COLINEAR_TOLERANCE:
        # 直线连接（误差小于线宽一半时视为共线）
        return [WireSegment(
            layer=wire_layer,
            points=[(ax, ay), (bx, by)],
            width=wire_width,
        )]
    else:
        # L型折线：先水平后垂直
        return [WireSegment(
            layer=wire_layer,
            points=[(ax, ay), (bx, ay), (bx, by)],
            width=wire_width,
        )]


def draw_wire_segments(
    cell: db.Cell,
    layout: db.Layout,
    wires: List[WireSegment],
) -> None:
    """将 WireSegment 列表绘制到 cell 中。

    Args:
        cell: 目标 Cell（通常是 top cell）
        layout: Layout 对象
        wires: WireSegment 列表
    """
    dbu = layout.dbu

    for wire in wires:
        layer_idx = layout.layer(*wire.layer)
        half_w = wire.width / 2.0

        for i in range(len(wire.points) - 1):
            x1, y1 = wire.points[i]
            x2, y2 = wire.points[i + 1]

            x1d, y1d = int(x1 / dbu), int(y1 / dbu)
            x2d, y2d = int(x2 / dbu), int(y2 / dbu)
            hwd = int(half_w / dbu)

            if abs(y1d - y2d) < max(1, hwd // 10):
                # 水平段
                box = db.Box(min(x1d, x2d), y1d - hwd, max(x1d, x2d), y1d + hwd)
                cell.shapes(layer_idx).insert(box)
            elif abs(x1d - x2d) < max(1, hwd // 10):
                # 垂直段
                box = db.Box(x1d - hwd, min(y1d, y2d), x1d + hwd, max(y1d, y2d))
                cell.shapes(layer_idx).insert(box)
            else:
                # 斜线：用 Path
                path = db.Path(
                    [db.Point(x1d, y1d), db.Point(x2d, y2d)],
                    hwd * 2,
                )
                cell.shapes(layer_idx).insert(path)


def erase_wire_segments(
    cell: db.Cell,
    layout: db.Layout,
    wires: List[WireSegment],
) -> None:
    """从 cell 中擦除指定的 WireSegment。

    Args:
        cell: 目标 Cell
        layout: Layout 对象
        wires: 要擦除的 WireSegment 列表
    """
    dbu = layout.dbu

    for wire in wires:
        layer_idx = layout.layer(*wire.layer)
        half_w = wire.width / 2.0

        erase_region = db.Region()
        for i in range(len(wire.points) - 1):
            x1, y1 = wire.points[i]
            x2, y2 = wire.points[i + 1]

            x1d, y1d = int(x1 / dbu), int(y1 / dbu)
            x2d, y2d = int(x2 / dbu), int(y2 / dbu)
            hwd = int(half_w / dbu)

            if abs(y1d - y2d) < max(1, hwd // 10):
                erase_region += db.Region(db.Box(min(x1d, x2d), y1d - hwd, max(x1d, x2d), y1d + hwd))
            elif abs(x1d - x2d) < max(1, hwd // 10):
                erase_region += db.Region(db.Box(x1d - hwd, min(y1d, y2d), x1d + hwd, max(y1d, y2d)))
            else:
                path = db.Path([db.Point(x1d, y1d), db.Point(x2d, y2d)], hwd * 2)
                erase_region += db.Region(path.bbox())

        if not erase_region.is_empty():
            shapes = cell.shapes(layer_idx)
            old_region = db.Region(shapes)
            new_region = old_region - erase_region
            shapes.clear()
            shapes.insert(new_region)


class InitialRouter:
    """初始布线器：根据网表和PCell引脚位置生成连线。"""

    def route_all(
        self,
        layout: db.Layout,
        top_cell: db.Cell,
        nets: List,  # List[Net] from parser
        ref_to_pcell: Dict[str, str],
        ref_to_params: Dict[str, dict],
        wire_width: float = DEFAULT_WIRE_WIDTH,
    ) -> Dict[str, List[WireSegment]]:
        """为所有网络生成连线。

        Args:
            layout: Layout 对象
            top_cell: 顶层 Cell
            nets: 网表网络列表
            ref_to_pcell: {ref: pcell_name}
            ref_to_params: {ref: geometry_params}
            wire_width: 走线宽度

        Returns:
            {net_name: [WireSegment, ...]} 所有网络的连线
        """
        # 1. 计算所有引脚的全局位置
        pin_states = self._compute_pin_states(layout, top_cell, nets, ref_to_pcell, ref_to_params)
        # 2. 获取各引脚的层信息
        pin_layers = self._compute_pin_layers(nets, ref_to_pcell, ref_to_params)

        # 3. 为每个网络布线
        all_wires: Dict[str, List[WireSegment]] = {}

        for net in nets:
            if len(net.nodes) < 2:
                continue

            # 获取该网络所有引脚
            net_pins = []
            for ref, pin_name in net.nodes:
                key = f"{ref}.{pin_name}"
                if key in pin_states:
                    net_pins.append(pin_states[key])

            if len(net_pins) < 2:
                continue

            # 对每对相邻引脚布线（链式连接）
            net_wires = []
            for i in range(len(net_pins) - 1):
                pa = net_pins[i]
                pb = net_pins[i + 1]
                layer_a = pin_layers.get(pa.key, DEFAULT_WIRE_LAYER)
                layer_b = pin_layers.get(pb.key, DEFAULT_WIRE_LAYER)
                wires = route_connection(pa, pb, layer_a, layer_b, wire_width)
                net_wires.extend(wires)

            all_wires[net.name] = net_wires
            logger.info(f"布线 {net.name}: {len(net_wires)} 段走线")

        return all_wires

    def route_affected_nets(
        self,
        layout: db.Layout,
        top_cell: db.Cell,
        nets: List,
        changed_refs: List[str],
        ref_to_pcell: Dict[str, str],
        ref_to_params: Dict[str, dict],
        old_wires: Optional[Dict[str, List[WireSegment]]] = None,
        wire_width: float = DEFAULT_WIRE_WIDTH,
    ) -> Dict[str, List[WireSegment]]:
        """为受影响网络重新布线。

        只重新布线涉及变更器件的网络，其他网络保持不变。

        Args:
            layout: Layout 对象
            top_cell: 顶层 Cell
            nets: 网表网络列表
            changed_refs: 变更器件的 reference 列表
            ref_to_pcell: {ref: pcell_name}
            ref_to_params: {ref: geometry_params}（新参数）
            old_wires: 旧连线信息 {net_name: [WireSegment]}，用于擦除
            wire_width: 走线宽度

        Returns:
            {net_name: [WireSegment, ...]} 受影响网络的新连线
        """
        changed_set = set(changed_refs)

        # 找出涉及变更器件的网络
        affected_nets = []
        for net in nets:
            for ref, pin_name in net.nodes:
                if ref in changed_set:
                    affected_nets.append(net)
                    break

        if not affected_nets:
            logger.info("无受影响网络")
            return {}

        # 擦除旧连线
        if old_wires:
            for net in affected_nets:
                if net.name in old_wires:
                    erase_wire_segments(top_cell, layout, old_wires[net.name])
                    logger.info(f"已擦除旧连线: {net.name}")

        # 重新布线
        return self.route_all(layout, top_cell, affected_nets, ref_to_pcell, ref_to_params, wire_width)

    def _compute_pin_states(
        self,
        layout: db.Layout,
        top_cell: db.Cell,
        nets: List,
        ref_to_pcell: Dict[str, str],
        ref_to_params: Dict[str, dict],
    ) -> Dict[str, PinState]:
        """计算所有引脚的全局位置。"""
        pin_states: Dict[str, PinState] = {}

        needed: Dict[str, set] = {}
        for net in nets:
            for ref, pin_name in net.nodes:
                needed.setdefault(ref, set()).add(pin_name)

        for ref, pin_names in needed.items():
            pcell_name = ref_to_pcell.get(ref)
            params = ref_to_params.get(ref, {})
            if not pcell_name or not params:
                continue

            try:
                pcell = get_pcell(pcell_name)
            except ValueError:
                continue

            local_pins = pcell.get_pin_positions(params)
            inst_trans = self._find_instance_transform(layout, top_cell, ref)

            for pin_name in pin_names:
                if pin_name not in local_pins:
                    continue
                pos = local_pins[pin_name]
                if inst_trans is not None:
                    local_pt = db.DPoint(pos.x, pos.y)
                    global_pt = inst_trans * local_pt
                    pin_states[f"{ref}.{pin_name}"] = PinState(
                        name=pin_name, ref=ref, x=global_pt.x, y=global_pt.y
                    )
                else:
                    pin_states[f"{ref}.{pin_name}"] = PinState(
                        name=pin_name, ref=ref, x=pos.x, y=pos.y
                    )

        return pin_states

    def _compute_pin_layers(
        self,
        nets: List,
        ref_to_pcell: Dict[str, str],
        ref_to_params: Dict[str, dict],
    ) -> Dict[str, Tuple[int, int]]:
        """获取各引脚的层信息。"""
        pin_layers: Dict[str, Tuple[int, int]] = {}

        needed: Dict[str, set] = {}
        for net in nets:
            for ref, pin_name in net.nodes:
                needed.setdefault(ref, set()).add(pin_name)

        for ref, pin_names in needed.items():
            pcell_name = ref_to_pcell.get(ref)
            params = ref_to_params.get(ref, {})
            if not pcell_name or not params:
                continue

            try:
                pcell = get_pcell(pcell_name)
            except ValueError:
                continue

            local_pins = pcell.get_pin_positions(params)
            for pin_name in pin_names:
                if pin_name in local_pins:
                    pin_layers[f"{ref}.{pin_name}"] = local_pins[pin_name].layer

        return pin_layers

    def _find_instance_transform(
        self, layout: db.Layout, top_cell: db.Cell, ref: str
    ) -> Optional[db.DCplxTrans]:
        """查找 ref 对应的 instance 变换。

        Cell 命名格式为 ref_pcell_name（如 C1_CAP_MIM）。
        用精确匹配避免 C1 错误匹配 C10。
        """
        for inst in top_cell.each_inst():
            cell = inst.cell
            if cell.name == ref:
                return inst.dcplx_trans
            # 避免 C1 错误匹配 C10：检查下划线后第一位不是数字
            if cell.name.startswith(f"{ref}_"):
                suffix = cell.name[len(ref) + 1:]
                if suffix and not suffix[0].isdigit():
                    return inst.dcplx_trans
        return None
