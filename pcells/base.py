"""PCell抽象基类，所有器件PCell必须实现此接口。"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

import klayout.db as db


@dataclass
class PinPosition:
    """引脚位置信息。"""
    name: str
    x: float  # um
    y: float  # um
    layer: Tuple[int, int]  # (layer, datatype) 引脚所在层


class BasePCell(abc.ABC):
    """所有PCell必须实现的接口。

    executor通过此接口统一调用PCell，不依赖具体器件实现。
    """

    @abc.abstractmethod
    def get_parameters(self) -> Dict[str, str]:
        """返回参数定义及类型。

        Returns:
            {"param_name": "type:unit"}，例: {"length": "float:um", "width": "float:um"}
        """
        ...

    @abc.abstractmethod
    def get_pins(self) -> List[str]:
        """返回引脚名列表。

        Returns:
            例: ["PI", "NIN"]
        """
        ...

    @abc.abstractmethod
    def get_pin_positions(self, params: dict) -> Dict[str, PinPosition]:
        """根据当前参数，返回各引脚的物理坐标。

        这是连线维护(stretch)的关键输入。

        Args:
            params: 当前PCell参数

        Returns:
            {pin_name: PinPosition}
        """
        ...

    @abc.abstractmethod
    def generate(self, cell: db.Cell, params: dict) -> None:
        """在KLayout cell对象中生成几何图形。

        调用前cell已被clear()，直接写入即可。

        Args:
            cell: KLayout Cell对象
            params: PCell参数
        """
        ...

    @abc.abstractmethod
    def validate_params(self, params: dict) -> Tuple[bool, List[str]]:
        """参数边界检查（与mapping_rules.yaml约束对齐）。

        Args:
            params: 待检查的参数

        Returns:
            (is_valid, error_messages)
        """
        ...

    @abc.abstractmethod
    def get_bounding_box(self, params: dict) -> Tuple[float, float, float, float]:
        """返回参数对应的包围盒 (x1, y1, x2, y2)，单位um。

        用途：
        1. StretchRouter判断连线是否需要拉伸
        2. DRC预检：新包围盒是否与邻近器件冲突

        Args:
            params: 当前PCell参数（含旋转角度等）

        Returns:
            (x1, y1, x2, y2) 左下角和右上角坐标
        """
        ...

    def get_required_layers(self) -> Dict[str, Tuple[int, int]]:
        """返回该PCell使用的层定义。

        Returns:
            {层名: (layer, datatype)}，子类可覆盖。
        """
        return {}

    def create_layers(self, layout: db.Layout) -> Dict[str, int]:
        """在layout中创建所需层，返回 {层名: layer_index}。

        Args:
            layout: KLayout Layout对象

        Returns:
            {层名: layer_index}
        """
        layer_indices = {}
        for name, (layer, datatype) in self.get_required_layers().items():
            layer_indices[name] = layout.layer(layer, datatype)
        return layer_indices

    # ─────────────────────────────────────────────────────────────────
    # LVS 引脚定位支持
    # ─────────────────────────────────────────────────────────────────

    PIN_MARKER_LAYER: Tuple[int, int] = (255, 0)  # 供 LVS 提取连通性专用层
    BROKEN_MARKER_LAYER: Tuple[int, int] = (200, 0)  # 断线标记层

    def _draw_pin_marker(self, cell: db.Cell, pin_name: str, x: float, y: float, size: float = 2.0):
        """在引脚位置画一个 2um 的 marker，供 LVS 提取连通性用。

        所有 PCell 的 generate() 必须调用此方法为每个引脚绘制 marker。
        该 marker 必须与引脚所在金属层有物理接触，interacting() 才能正确检出。

        Args:
            cell: KLayout Cell 对象
            pin_name: 引脚名称
            x: 引脚全局 x 坐标 (um)
            y: 引脚全局 y 坐标 (um)
            size: marker 边长 (um)，默认 2um
        """
        dbu = cell.layout().dbu
        half = int(size / 2.0 / dbu)
        cx = int(x / dbu)
        cy = int(y / dbu)
        marker_layer = cell.layout().layer(db.LayerInfo(*self.PIN_MARKER_LAYER))
        cell.shapes(marker_layer).insert(
            db.Box(cx - half, cy - half, cx + half, cy + half)
        )
        # 同时画文本标签，供LVS查找pin名称和坐标
        cell.shapes(marker_layer).insert(
            db.Text(pin_name, db.Trans(db.Point(cx, cy)))
        )
