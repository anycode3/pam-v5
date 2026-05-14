"""方形螺旋电感PCell实现。

结构：方形螺旋走线(顶层金属) + Underpass(底层金属跨越) + 通孔连接

引脚：
    PI:  外圈顶端中心（顶层金属引出）
    NIN: 外圈底端偏左（底层金属Underpass引出）

参数：
    inner_radius: 内圈半宽 (um)
    turns:        圈数，支持半圈如2.5/3.5
    width:        走线宽度 (um)
    spacing:      圈间距 (um)
    angle:        旋转角度 (deg)
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import klayout.db as db

from pcells.base import BasePCell, PinPosition
from pcells.registry import register


@register("IND_SPIRAL")
class SpiralInductor(BasePCell):
    """方形螺旋电感PCell。"""

    LAYERS = {
        "METAL_TOP":    (7, 0),   # 顶层走线（螺旋主体）
        "METAL_UNDER":  (6, 0),   # 底层走线（Underpass）
        "VIA":          (11, 0),  # 层间通孔
        "PIN":          (100, 0), # 引脚标记层
    }

    def get_parameters(self) -> Dict[str, str]:
        return {
            "inner_radius": "float:um",
            "turns":        "float",
            "width":        "float:um",
            "spacing":      "float:um",
            "angle":        "float:deg",
        }

    def get_pins(self) -> List[str]:
        return ["PI", "NIN"]

    def get_pin_positions(self, params: dict) -> Dict[str, PinPosition]:
        """引脚位置：PI外圈顶部，NIN外圈底部偏左(Underpass引出)。"""
        ir = params["inner_radius"]
        n = params["turns"]
        w = params["width"]
        s = params["spacing"]
        angle = params.get("angle", 0.0)

        total_exp = (math.ceil(n) - 1) * (w + s)
        outer_half = ir + total_exp + w

        # 本地坐标
        pi_local = (0.0, outer_half)
        nin_local = (-ir, -outer_half)

        # 旋转
        rad = math.radians(angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)

        def rotate(px, py):
            return (px * cos_a - py * sin_a, px * sin_a + py * cos_a)

        pi_r = rotate(*pi_local)
        nin_r = rotate(*nin_local)

        return {
            "PI": PinPosition(name="PI", x=pi_r[0], y=pi_r[1], layer=self.LAYERS["METAL_TOP"]),
            "NIN": PinPosition(name="NIN", x=nin_r[0], y=nin_r[1], layer=self.LAYERS["METAL_UNDER"]),
        }

    def generate(self, cell: db.Cell, params: dict) -> None:
        """生成分段走线+Underpass+通孔。"""
        ir = params["inner_radius"]
        n = params["turns"]
        w = params["width"]
        s = params["spacing"]
        angle = params.get("angle", 0.0)

        layout = cell.layout()
        dbu = layout.dbu

        layer_top = layout.layer(*self.LAYERS["METAL_TOP"])
        layer_under = layout.layer(*self.LAYERS["METAL_UNDER"])
        layer_via = layout.layer(*self.LAYERS["VIA"])
        layer_pin = layout.layer(*self.LAYERS["PIN"])

        # 旋转变换
        rot_code = int(round(angle / 90.0)) % 4 if angle != 0 else 0
        trans = db.Trans(rot_code, False, 0, 0) if rot_code != 0 else None

        # 计算并绘制螺旋走线
        segments = self._compute_spiral_segments(ir, n, w, s)
        for seg in segments:
            self._draw_segment(cell, layer_top, seg, w, dbu, trans)

        # 绘制Underpass
        underpass = self._compute_underpass(ir, n, w, s)
        self._draw_segment(cell, layer_under, underpass, w, dbu, trans)

        # 绘制通孔
        vias = self._compute_vias(ir, n, w, s)
        for vx, vy in vias:
            self._draw_via(cell, layer_via, vx, vy, w, dbu, trans)

        # 引脚标记
        pins = self.get_pin_positions(params)
        for pin_name, pin_pos in pins.items():
            px = int(pin_pos.x / dbu)
            py = int(pin_pos.y / dbu)
            cell.shapes(layer_pin).insert(
                db.Box(px - int(1 / dbu), py - int(1 / dbu), px + int(1 / dbu), py + int(1 / dbu))
            )
            cell.shapes(layer_pin).insert(
                db.Text(pin_name, db.Trans(db.Point(px, py)))
            )

        # LVS pin markers（PIN_MARKER_LAYER）
        for pin_name, pin_pos in pins.items():
            self._draw_pin_marker(cell, pin_name, pin_pos.x, pin_pos.y)

    def _compute_spiral_segments(self, ir: float, n: float, w: float, s: float) -> List[Tuple]:
        """计算方形螺旋的所有走线段。

        返回: [(x1, y1, x2, y2, direction), ...]
        direction: "H" 水平, "V" 垂直

        绘制顺序：从内圈开始，每圈顶→右→底→左
        """
        segments = []
        half_w = w / 2.0
        full_turns = int(n)
        has_half = (n - full_turns) >= 0.5

        for turn in range(full_turns):
            off = turn * (w + s)

            # 当前圈的四边中心线坐标
            top_y = ir + off + half_w
            right_x = ir + off + half_w
            bottom_y = -(ir + off + half_w)
            left_x = -(ir + off + half_w)

            shrink = w + s  # 螺旋内缩量

            # 顶边：水平向右
            if turn == 0:
                x_start = -right_x  # 第一圈：完整顶边
            else:
                x_start = left_x + shrink  # 后续圈：从左边终点向右偏移
            segments.append((x_start, top_y, right_x, top_y, "H"))

            # 右边：垂直向下
            segments.append((right_x, top_y, right_x, bottom_y, "V"))

            # 底边：水平向左（内缩）
            segments.append((right_x, bottom_y, left_x + shrink, bottom_y, "H"))

            # 左边：垂直向上→连接下一圈
            next_top_y = ir + (turn + 1) * (w + s) + half_w
            segments.append((left_x, bottom_y, left_x, next_top_y, "V"))

        # 半圈：只有顶边
        if has_half:
            off = full_turns * (w + s)
            top_y = ir + off + half_w
            right_x = ir + off + half_w

            # 左边终点就是半圈顶边的起点
            if full_turns > 0:
                prev_left_x = -(ir + (full_turns - 1) * (w + s) + half_w)
                x_start = prev_left_x
            else:
                x_start = -right_x

            segments.append((x_start, top_y, right_x, top_y, "H"))

        return segments

    def _compute_underpass(self, ir: float, n: float, w: float, s: float) -> Tuple:
        """计算Underpass路径：从中心底端跨越到外圈底部。"""
        total_exp = (math.ceil(n) - 1) * (w + s)
        outer_bottom_y = -(ir + total_exp + w / 2.0)
        x_underpass = -ir  # 偏左，避免与左边走线短路

        return (x_underpass, 0.0, x_underpass, outer_bottom_y, "V")

    def _compute_vias(self, ir: float, n: float, w: float, s: float) -> List[Tuple]:
        """计算通孔位置：Underpass两端各一个。"""
        total_exp = (math.ceil(n) - 1) * (w + s)
        outer_bottom_y = -(ir + total_exp + w / 2.0)
        x = -ir

        return [
            (x, 0.0),              # 顶端通孔（螺旋起点→Underpass起点）
            (x, outer_bottom_y),   # 底端通孔（Underpass终点→外圈底部）
        ]

    def _draw_segment(
        self, cell: db.Cell, layer: int,
        seg: Tuple, width: float, dbu: float,
        trans: db.Trans = None,
    ) -> None:
        """绘制一条走线段。"""
        x1, y1, x2, y2, direction = seg
        half_w = width / 2.0

        # um → dbu
        x1d, y1d, x2d, y2d = (
            int(x1 / dbu), int(y1 / dbu),
            int(x2 / dbu), int(y2 / dbu),
        )
        hwd = int(half_w / dbu)

        if direction == "H":
            box = db.Box(min(x1d, x2d), y1d - hwd, max(x1d, x2d), y1d + hwd)
        else:
            box = db.Box(x1d - hwd, min(y1d, y2d), x1d + hwd, max(y1d, y2d))

        if trans is not None:
            cell.shapes(layer).insert(trans * box)
        else:
            cell.shapes(layer).insert(box)

    def _draw_via(
        self, cell: db.Cell, layer: int,
        vx: float, vy: float, width: float, dbu: float,
        trans: db.Trans = None,
    ) -> None:
        """绘制通孔。"""
        hwd = int(width / 2.0 / dbu)
        vxd, vyd = int(vx / dbu), int(vy / dbu)
        box = db.Box(vxd - hwd, vyd - hwd, vxd + hwd, vyd + hwd)

        if trans is not None:
            cell.shapes(layer).insert(trans * box)
        else:
            cell.shapes(layer).insert(box)

    def validate_params(self, params: dict) -> Tuple[bool, List[str]]:
        """参数边界检查。"""
        errors = []
        ir = params.get("inner_radius", 0)
        n = params.get("turns", 0)
        w = params.get("width", 0)
        s = params.get("spacing", 0)

        if ir < 20 or ir > 80:
            errors.append(f"inner_radius={ir} 超出范围 [20, 80] um")
        if n < 1.5 or n > 6.5:
            errors.append(f"turns={n} 超出范围 [1.5, 6.5]")
        if w < 5 or w > 20:
            errors.append(f"width={w} 超出范围 [5, 20] um")
        if s < 5 or s > 15:
            errors.append(f"spacing={s} 超出范围 [5, 15] um")

        return len(errors) == 0, errors

    def get_bounding_box(self, params: dict) -> Tuple[float, float, float, float]:
        """包围盒：方形，中心对称。"""
        ir = params["inner_radius"]
        n = params["turns"]
        w = params["width"]
        s = params["spacing"]
        angle = params.get("angle", 0.0)

        total_exp = (math.ceil(n) - 1) * (w + s)
        outer_half = ir + total_exp + w

        # 无旋转时直接返回
        if angle == 0.0:
            return (-outer_half, -outer_half, outer_half, outer_half)

        # 有旋转时计算旋转后的bbox
        corners = [
            (-outer_half, -outer_half), (outer_half, -outer_half),
            (outer_half, outer_half), (-outer_half, outer_half),
        ]
        rad = math.radians(angle)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        rotated = [(x * cos_a - y * sin_a, x * sin_a + y * cos_a) for x, y in corners]
        xs = [p[0] for p in rotated]
        ys = [p[1] for p in rotated]
        return (min(xs), min(ys), max(xs), max(ys))

    def get_required_layers(self) -> Dict[str, Tuple[int, int]]:
        return self.LAYERS
