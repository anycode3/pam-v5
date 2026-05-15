"""引脚坐标提取器：从 GDS 版图中提取器件引脚的全局坐标。

通过扫描子 cell 的 PIN marker 层 (255/0) 上的文本标签，
结合 instance 变换，计算引脚在 top cell 中的全局坐标。

无需依赖快照，每次从版图实时读取。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import klayout.db as db

logger = logging.getLogger(__name__)

# PIN marker 层（BasePCell.PIN_MARKER_LAYER）
PIN_MARKER_LAYER = (255, 0)


def extract_pin_positions(
    layout: db.Layout,
    top_cell: db.Cell,
) -> Dict[str, Dict[str, Tuple[float, float]]]:
    """从 GDS 版图中提取所有器件引脚的全局坐标。

    Args:
        layout: KLayout Layout 对象
        top_cell: 顶层 Cell

    Returns:
        {ref: {pin_name: (x_um, y_um)}}

    示例:
        {"C1": {"PI": (67.0, 28.5), "NIN": (67.0, 5.0)},
         "TL1": {"P1": (50.0, 0.0), "P2": (2050.0, 0.0)}}
    """
    dbu = layout.dbu
    marker_layer = layout.layer(db.LayerInfo(*PIN_MARKER_LAYER))

    result: Dict[str, Dict[str, Tuple[float, float]]] = {}

    for inst in top_cell.each_inst():
        cell = inst.cell
        trans = inst.dcplx_trans  # DCplxTrans，微米空间

        # 从 cell 名提取 ref（如 "C1_CAP_MIM" → "C1"）
        ref = _extract_ref_from_cell_name(cell.name)
        if ref is None:
            continue

        pins: Dict[str, Tuple[float, float]] = {}

        for shape in cell.shapes(marker_layer).each():
            if shape.is_text():
                text_obj = shape.text
                pin_name = text_obj.string

                # 本地坐标 → 全局坐标（微米空间）
                local_pt = db.DPoint(text_obj.x * dbu, text_obj.y * dbu)
                global_pt = trans * local_pt

                pins[pin_name] = (global_pt.x, global_pt.y)

        if pins:
            result[ref] = pins

    return result


def extract_pin_layers(
    layout: db.Layout,
    top_cell: db.Cell,
) -> Dict[str, Dict[str, Tuple[int, int]]]:
    """从 GDS 版图中提取引脚所属的金属层。

    通过在引脚坐标附近查找子 cell 中重叠的金属形状来确定层。

    Args:
        layout: KLayout Layout 对象
        top_cell: 顶层 Cell

    Returns:
        {ref: {pin_name: (layer, datatype)}}
    """
    dbu = layout.dbu
    marker_layer = layout.layer(db.LayerInfo(*PIN_MARKER_LAYER))

    # 收集子 cell 的金属层索引
    metal_layers = _collect_metal_layers(layout, top_cell)

    result: Dict[str, Dict[str, Tuple[int, int]]] = {}

    for inst in top_cell.each_inst():
        cell = inst.cell
        ref = _extract_ref_from_cell_name(cell.name)
        if ref is None:
            continue

        pin_layers_map: Dict[str, Tuple[int, int]] = {}

        for shape in cell.shapes(marker_layer).each():
            if shape.is_text():
                pin_name = shape.text.string
                # 在引脚坐标附近查找金属层形状
                local_pt = db.Point(shape.text.x, shape.text.y)
                query_box = db.Box(
                    local_pt.x - int(2.0 / dbu),
                    local_pt.y - int(2.0 / dbu),
                    local_pt.x + int(2.0 / dbu),
                    local_pt.y + int(2.0 / dbu),
                )

                for layer_idx in metal_layers:
                    layer_info = layout.get_info(layer_idx)
                    query_region = db.Region(query_box)
                    cell_region = db.Region(cell.shapes(layer_idx))
                    if not (query_region & cell_region).is_empty():
                        pin_layers_map[pin_name] = (layer_info.layer, layer_info.datatype)
                        break

        if pin_layers_map:
            result[ref] = pin_layers_map

    return result


def _extract_ref_from_cell_name(cell_name: str) -> Optional[str]:
    """从 cell 名提取器件 reference。

    规则："C1_CAP_MIM" → "C1"，"TL1_TL_MICROSTRIP" → "TL1"
    取第一个下划线前的部分。
    """
    if "_" in cell_name:
        return cell_name.split("_")[0]
    return cell_name if cell_name else None


def _collect_metal_layers(
    layout: db.Layout,
    top_cell: db.Cell,
) -> List[int]:
    """收集版图中使用的金属层索引。"""
    metal_layer_nums = {2, 6, 7, 8, 10}  # GND, METAL_UNDER, METAL_TOP, MB, MT
    metal_layers = []
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if info.layer in metal_layer_nums:
            metal_layers.append(li)
    return metal_layers
