"""连线提取器：从 GDS 版图的 top cell 中提取走线几何。

top cell 上直接绘制的形状就是连线（区别于子 cell 中的器件几何）。
提取后返回 {net_name: [WireSegment]}，供重建连线时擦除使用。

无需依赖快照，每次从版图实时读取。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import klayout.db as db

from .types import WireSegment
from .pin_extractor import extract_pin_positions, PIN_MARKER_LAYER

logger = logging.getLogger(__name__)

# 未接触引脚的 shape 归属最近网络的距离阈值 (μm)
NEAREST_NET_DISTANCE_THRESHOLD_UM = 20.0


def extract_wires_from_gds(
    layout: db.Layout,
    top_cell: db.Cell,
    nets: List,
) -> Dict[str, List[WireSegment]]:
    """从 GDS 版图的 top cell 提取连线，按网络名分组。

    算法：
    1. 提取所有引脚全局坐标
    2. 遍历 top cell 上每个金属层的 shapes
    3. 对每个 shape，检查它连接了哪些引脚
    4. 将连接了同一对引脚的 shapes 归入同一网络

    Args:
        layout: KLayout Layout 对象
        top_cell: 顶层 Cell
        nets: 网表网络列表（用于确定网络名）

    Returns:
        {net_name: [WireSegment, ...]}
    """
    dbu = layout.dbu
    pin_positions = extract_pin_positions(layout, top_cell)

    # 构建 pin 全局坐标 → (ref, pin_name) 的反向映射
    coord_to_pin: Dict[Tuple[float, float], Tuple[str, str]] = {}
    for ref, pins in pin_positions.items():
        for pin_name, (x, y) in pins.items():
            coord_to_pin[(round(x, 2), round(y, 2))] = (ref, pin_name)

    # 收集 top cell 上的金属层 shapes（排除 marker/text 层）
    excluded_layers = {100, 255, 200}  # PIN, PIN_MARKER, BROKEN_MARKER
    # 用 (layer, datatype, bbox) 统一表示所有形状类型
    metal_shapes: List[Tuple[int, int, db.Box]] = []

    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if info.layer in excluded_layers:
            continue
        if top_cell.shapes(li).size() == 0:
            continue

        for shape in top_cell.shapes(li).each():
            bbox = shape.bbox()
            if bbox.empty():
                continue
            metal_shapes.append((info.layer, info.datatype, bbox))

    if not metal_shapes:
        return {}

    # 对每个 shape，找它接触的引脚
    shape_pins: List[List[Tuple[str, str]]] = []  # 每个shape接触的引脚列表
    for layer_num, datatype, box in metal_shapes:
        touched_pins = []
        # 用 box 扩展区域查询引脚
        margin = int(1.0 / dbu)  # 1um 容差
        query_box = db.Box(box.left - margin, box.bottom - margin,
                          box.right + margin, box.top + margin)

        for (px, py), (ref, pin_name) in coord_to_pin.items():
            px_dbu = int(px / dbu)
            py_dbu = int(py / dbu)
            pt = db.Point(px_dbu, py_dbu)
            if query_box.contains(pt):
                touched_pins.append((ref, pin_name))

        shape_pins.append(touched_pins)

    # 按网络分组：将连接同一对引脚的 shapes 归为一组
    net_to_shapes: Dict[str, List[Tuple[int, int, db.Box]]] = {}

    # 先构建网表的反向索引：(ref, pin_name) → net_name
    pin_to_net: Dict[Tuple[str, str], str] = {}
    for net in nets:
        for ref, pin_name in net.nodes:
            pin_to_net[(ref, pin_name)] = net.name

    # 将 shapes 映射到网络
    shape_net_names: List[Optional[str]] = []
    for i, (layer_num, datatype, box) in enumerate(metal_shapes):
        pins = shape_pins[i]
        net_name = None

        # 如果 shape 接触的引脚都在同一网络，归属该网络
        if pins:
            nets_found = set()
            for ref, pin_name in pins:
                key = (ref, pin_name)
                if key in pin_to_net:
                    nets_found.add(pin_to_net[key])
            if len(nets_found) == 1:
                net_name = nets_found.pop()
            elif len(nets_found) > 1:
                # 连接了多个网络的 shape（短路情况），取第一个
                net_name = sorted(nets_found)[0]
                logger.warning(f"Shape on layer {layer_num} touches multiple nets: {nets_found}")
        else:
            # 没有直接接触引脚，尝试通过空间关系归入最近网络
            net_name = _find_nearest_net(box, pin_positions, pin_to_net, dbu)

        shape_net_names.append(net_name)

    # 按网络名聚合 shapes，转为 WireSegment
    result: Dict[str, List[WireSegment]] = {}
    for i, (layer_num, datatype, box) in enumerate(metal_shapes):
        net_name = shape_net_names[i]
        if net_name is None:
            continue

        x1 = box.left * dbu
        y1 = box.bottom * dbu
        x2 = box.right * dbu
        y2 = box.top * dbu

        # 判断方向
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        if dx > dy:
            # 水平走线
            width = y2 - y1
            cy = (y1 + y2) / 2.0
            points = [(x1, cy), (x2, cy)]
        else:
            # 垂直走线
            width = x2 - x1
            cx = (x1 + x2) / 2.0
            points = [(cx, y1), (cx, y2)]

        wire = WireSegment(
            layer=(layer_num, datatype),
            points=points,
            width=width,
        )
        result.setdefault(net_name, []).append(wire)

    for net_name, wires in result.items():
        logger.info(f"提取连线: {net_name} ({len(wires)} 段)")

    return result


def erase_wires_from_top_cell(
    layout: db.Layout,
    top_cell: db.Cell,
    nets_to_erase: List[str],
    wires: Dict[str, List[WireSegment]],
) -> None:
    """从 top cell 擦除指定网络的连线。

    Args:
        layout: KLayout Layout 对象
        top_cell: 顶层 Cell
        nets_to_erase: 要擦除的网络名列表
        wires: 从 extract_wires_from_gds 获取的连线数据
    """
    dbu = layout.dbu

    for net_name in nets_to_erase:
        if net_name not in wires:
            continue

        for wire in wires[net_name]:
            layer_idx = layout.layer(*wire.layer)
            erase_region = db.Region()

            half_w = wire.width / 2.0
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

            if not erase_region.is_empty():
                shapes = top_cell.shapes(layer_idx)
                old_region = db.Region(shapes)
                new_region = old_region - erase_region
                shapes.clear()
                shapes.insert(new_region)

        logger.info(f"已擦除连线: {net_name}")


def _find_nearest_net(
    box: db.Box,
    pin_positions: Dict[str, Dict[str, Tuple[float, float]]],
    pin_to_net: Dict[Tuple[str, str], str],
    dbu: float,
) -> Optional[str]:
    """为没有直接接触引脚的 shape 找最近网络。"""
    cx = (box.left + box.right) / 2 * dbu
    cy = (box.bottom + box.top) / 2 * dbu

    min_dist = float("inf")
    nearest_net = None

    for ref, pins in pin_positions.items():
        for pin_name, (px, py) in pins.items():
            dist = (cx - px) ** 2 + (cy - py) ** 2
            if dist < min_dist:
                min_dist = dist
                key = (ref, pin_name)
                if key in pin_to_net:
                    nearest_net = pin_to_net[key]

    # 只在距离足够近时才归属（阈值内）
    threshold_sq = NEAREST_NET_DISTANCE_THRESHOLD_UM ** 2
    if min_dist < threshold_sq:
        return nearest_net
    return None
