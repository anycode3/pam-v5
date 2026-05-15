"""MIM电容PCell实现。

结构：
    顶层金属板 (MT) ─── PI引脚
    │  介质层 (MIM_DIELECTRIC)
    底层金属板 (MB) ─── NIN引脚
    通孔阵列连接引脚到外部布线

参数：
    length: 电容板长度 (um)
    width:  电容板宽度 (um)
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import klayout.db as db

from pcells.base import BasePCell, PinPosition
from pcells.registry import register


@register("CAP_MIM")
class MIMCapacitor(BasePCell):
    """MIM电容PCell。"""

    # 层定义（通用，无PDK依赖）
    LAYERS = {
        "MT":  (10, 0),    # 顶层金属（上极板）
        "MB":  (8, 0),     # 底层金属（下极板）
        "MIM": (9, 0),     # MIM介质层标记
        "VIA": (9, 1),     # 通孔层
        "PIN": (100, 0),   # 引脚标记层
    }

    # 工艺参数（通用默认值，实际PDK中需替换）
    VIA_SIZE = 2.0        # um, 通孔尺寸
    VIA_PITCH = 4.0       # um, 通孔间距
    PIN_LENGTH = 10.0     # um, 引脚延伸长度

    def get_parameters(self) -> Dict[str, str]:
        return {
            "length": "float:um",
            "width": "float:um",
        }

    def get_pins(self) -> List[str]:
        return ["PI", "NIN"]

    def get_pin_positions(self, params: dict) -> Dict[str, PinPosition]:
        """引脚位置：PI在上极板右端中间，NIN在下极板右端底部中间。"""
        length = params["length"]
        width = params["width"]
        pin_len = self.PIN_LENGTH
        nin_w = min(width * 0.3, 10.0)  # NIN引脚延伸宽度，与generate()一致

        return {
            "PI": PinPosition(
                name="PI",
                x=length + pin_len,
                y=width / 2,  # 上极板右端中间
                layer=self.LAYERS["MT"],
            ),
            "NIN": PinPosition(
                name="NIN",
                x=length + pin_len,
                y=nin_w / 2.0,  # 下极板引脚延伸的纵向中心
                layer=self.LAYERS["MB"],
            ),
        }

    def generate(self, cell: db.Cell, params: dict) -> None:
        """生成MIM电容几何。"""
        length = params["length"]
        width = params["width"]
        pin_len = self.PIN_LENGTH

        dbu = cell.layout().dbu

        # 上极板 (MT) + PI引脚延伸
        mt_layer = cell.layout().layer(*self.LAYERS["MT"])
        # 极板
        plate_l = int(length / dbu)
        plate_w = int(width / dbu)
        cell.shapes(mt_layer).insert(db.Box(0, 0, plate_l, plate_w))
        # PI引脚延伸（右侧中间走线）
        pin_ext = int(pin_len / dbu)
        pin_w = int(min(width * 0.3, 10.0) / dbu)  # 引脚宽度=min(30%极板宽, 10um)
        pin_y = (plate_w - pin_w) // 2
        cell.shapes(mt_layer).insert(db.Box(plate_l, pin_y, plate_l + pin_ext, pin_y + pin_w))

        # 下极板 (MB) + NIN引脚延伸
        mb_layer = cell.layout().layer(*self.LAYERS["MB"])
        # 极板（与上极板同尺寸）
        cell.shapes(mb_layer).insert(db.Box(0, 0, plate_l, plate_w))
        # NIN引脚延伸（右侧下端走线）
        nin_ext = int(pin_len / dbu)
        nin_w = pin_w
        nin_y = 0  # NIN在底部
        cell.shapes(mb_layer).insert(db.Box(plate_l, nin_y, plate_l + nin_ext, nin_y + nin_w))

        # MIM介质层标记
        mim_layer = cell.layout().layer(*self.LAYERS["MIM"])
        cell.shapes(mim_layer).insert(db.Box(0, 0, plate_l, plate_w))

        # 通孔阵列（连接上下极板区域外围，实际MIM电容通孔在引脚区域）
        via_layer = cell.layout().layer(*self.LAYERS["VIA"])
        via_size = int(self.VIA_SIZE / dbu)
        via_pitch = int(self.VIA_PITCH / dbu)

        # 在PI引脚区域放通孔
        self._place_via_array(
            cell, via_layer,
            x_start=plate_l, y_start=pin_y,
            x_end=plate_l + pin_ext, y_end=pin_y + pin_w,
            via_size=via_size, via_pitch=via_pitch,
        )

        # 引脚标记（用于LVS和连线定位）
        pin_layer = cell.layout().layer(*self.LAYERS["PIN"])
        pins = self.get_pin_positions(params)
        for pin_name, pin_pos in pins.items():
            px = int(pin_pos.x / dbu)
            py = int(pin_pos.y / dbu)
            pin_l = cell.layout().layer(*pin_pos.layer)
            # 引脚标记：小矩形 + 文本
            cell.shapes(pin_layer).insert(
                db.Box(px - int(1/dbu), py - int(1/dbu), px + int(1/dbu), py + int(1/dbu))
            )
            cell.shapes(pin_layer).insert(
                db.Text(pin_name, db.Trans(db.Point(px, py)))
            )

        # LVS pin markers（PIN_MARKER_LAYER）
        for pin_name, pin_pos in pins.items():
            self._draw_pin_marker(cell, pin_name, pin_pos.x, pin_pos.y)

    def validate_params(self, params: dict, constraints: dict = None) -> Tuple[bool, List[str]]:
        """参数边界检查。

        Args:
            params: 待检查的几何参数
            constraints: 约束边界，格式 {param: {min, max}}。
                        如果为 None 或某参数无约束，则该项不检查。

        Returns:
            (is_valid, error_messages)
        """
        if constraints is None:
            constraints = {}

        errors = []

        for param_name in ["length", "width"]:
            value = params.get(param_name)
            if value is None:
                continue
            bounds = constraints.get(param_name, {})
            min_val = bounds.get("min")
            max_val = bounds.get("max")
            if min_val is not None and value < min_val:
                errors.append(f"{param_name}={value} 低于下限 {min_val}")
            if max_val is not None and value > max_val:
                errors.append(f"{param_name}={value} 超过上限 {max_val}")

        return len(errors) == 0, errors

    def get_bounding_box(self, params: dict) -> Tuple[float, float, float, float]:
        """包围盒：含引脚延伸区域。"""
        length = params["length"]
        width = params["width"]
        pin_len = self.PIN_LENGTH
        # NIN延伸在左侧(-pin_len)，PI延伸在右侧(length+pin_len)
        return (-pin_len, 0, length + pin_len, width)

    def _place_via_array(
        self,
        cell: db.Cell,
        via_layer: int,
        x_start: int, y_start: int,
        x_end: int, y_end: int,
        via_size: int, via_pitch: int,
    ) -> None:
        """在指定区域内放置通孔阵列。"""
        half = via_size // 2
        x = x_start + via_pitch
        while x + half < x_end:
            y = y_start + via_pitch
            while y + half < y_end:
                cell.shapes(via_layer).insert(
                    db.Box(x - half, y - half, x + half, y + half)
                )
                y += via_pitch
            x += via_pitch

    def get_required_layers(self) -> Dict[str, Tuple[int, int]]:
        return self.LAYERS
