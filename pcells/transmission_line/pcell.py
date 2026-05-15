"""微带传输线PCell实现。

结构：
    P1 ───────────────── P2
    ├─ 金属带线 (width × length) ─┤

有方向器件：P1(入) → P2(出)，不可互换。
支持旋转：angle=0°(水平), 90°(垂直), 180°, 270°。

参数：
    width:  线宽 (um) → 决定特征阻抗
    length: 线长 (um) → 决定电长度
    angle:  旋转角度 (deg)，默认0
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import klayout.db as db

from pcells.base import BasePCell, PinPosition
from pcells.registry import register


@register("TL_MICROSTRIP")
class TransmissionLine(BasePCell):
    """微带传输线PCell，支持旋转。"""

    # 层定义
    LAYERS = {
        "METAL": (6, 0),    # 信号层金属
        "GND":   (2, 0),    # 地层（参考面，简化版不画）
        "PIN":   (100, 0),  # 引脚标记层
    }

    # TAPER_LENGTH: 引脚处渐变过渡长度 (um)
    TAPER_LENGTH = 5.0

    def get_parameters(self) -> Dict[str, str]:
        return {
            "width":  "float:um",
            "length": "float:um",
            "angle":  "float:deg",
        }

    def get_pins(self) -> List[str]:
        return ["P1", "P2"]

    def get_pin_positions(self, params: dict) -> Dict[str, PinPosition]:
        """根据参数和旋转角度计算引脚绝对坐标。

        本地坐标(0°): P1在左端中心, P2在右端中心
        """
        w = params["width"]
        l = params["length"]
        angle = params.get("angle", 0.0)

        # 本地坐标
        p1_local = (0.0, 0.0)
        p2_local = (l, 0.0)

        # 旋转
        rad = math.radians(angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)

        def rotate(px, py):
            return (px * cos_a - py * sin_a, px * sin_a + py * cos_a)

        p1_rot = rotate(*p1_local)
        p2_rot = rotate(*p2_local)

        return {
            "P1": PinPosition(name="P1", x=p1_rot[0], y=p1_rot[1], layer=self.LAYERS["METAL"]),
            "P2": PinPosition(name="P2", x=p2_rot[0], y=p2_rot[1], layer=self.LAYERS["METAL"]),
        }

    def generate(self, cell: db.Cell, params: dict) -> None:
        """生成微带线几何，含旋转变换。"""
        w = params["width"]
        l = params["length"]
        angle = params.get("angle", 0.0)

        dbu = cell.layout().dbu
        metal_layer = cell.layout().layer(*self.LAYERS["METAL"])
        pin_layer = cell.layout().layer(*self.LAYERS["PIN"])

        # 本地坐标矩形：中心线沿x轴，宽度居中
        # (0, -w/2) → (l, w/2)
        w_dbu = int(w / dbu)
        l_dbu = int(l / dbu)
        half_w = w_dbu // 2
        rect = db.Box(0, -half_w, l_dbu, half_w)

        # 旋转变换：KLayout的Trans(rot, mirror, dx, dy)
        # rot = 0/1/2/3 对应 0°/90°/180°/270°
        rot_code = int(round(angle / 90.0)) % 4
        trans = db.Trans(rot_code, False, 0, 0)
        cell.shapes(metal_layer).insert(trans * rect)

        # 引脚标记
        pins = self.get_pin_positions(params)
        for pin_name, pin_pos in pins.items():
            px = int(pin_pos.x / dbu)
            py = int(pin_pos.y / dbu)
            # 引脚标记点
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

        for param_name in ["width", "length"]:
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

        # angle 来自 YAML defaults，不从 constraints 检查，是固定的几何合法性校验
        angle = params.get("angle", 0)
        if angle < 0 or angle >= 360:
            errors.append(f"angle={angle} 超出范围 [0, 360) deg")

        return len(errors) == 0, errors

    def get_bounding_box(self, params: dict) -> Tuple[float, float, float, float]:
        """返回旋转后的包围盒 (x1, y1, x2, y2)，单位um。"""
        w = params["width"]
        l = params["length"]
        angle = params.get("angle", 0.0)
        half_w = w / 2

        # 本地坐标四角
        corners = [
            (0, -half_w), (l, -half_w),
            (l, half_w), (0, half_w),
        ]

        # 旋转
        rad = math.radians(angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        rotated = [
            (x * cos_a - y * sin_a, x * sin_a + y * cos_a)
            for x, y in corners
        ]

        xs = [p[0] for p in rotated]
        ys = [p[1] for p in rotated]
        return (min(xs), min(ys), max(xs), max(ys))

    def get_required_layers(self) -> Dict[str, Tuple[int, int]]:
        return self.LAYERS
