"""连线维护策略抽象基类与StretchRouter实现。

使用 klayout.db headless API。
StretchRouter：基于引脚位移的增量拉伸，支持直线和L型折线。
"""

from __future__ import annotations

import abc
import logging
import math

logger = logging.getLogger(__name__)
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from pcells.base import BasePCell

import klayout.db as db

from .types import PinState, WireSegment, Connection, StretchResult


@dataclass
class RoutingResult:
    """连线维护结果。"""
    success: bool
    modified_paths: list[str] = field(default_factory=list)
    needs_manual_fix: list[str] = field(default_factory=list)
    message: str = ""
    stretch_result: Optional[StretchResult] = None


class RoutingStrategy(abc.ABC):
    """连线维护策略抽象基类。"""

    @abc.abstractmethod
    def maintain(
        self,
        layout: db.Layout,
        cell: db.Cell,
        old_pins: dict[str, db.DPoint],
        new_pins: dict[str, db.DPoint],
        threshold_dbu: float,
    ) -> RoutingResult:
        """根据引脚新旧位置维护连线。"""
        ...

    @abc.abstractmethod
    def stretch_connections(
        self,
        layout: db.Layout,
        cell: db.Cell,
        connections: List[Connection],
        old_pins: Dict[str, PinState],
        new_pins: Dict[str, PinState],
        threshold_um: float,
    ) -> StretchResult:
        """基于Connection对象的拉伸接口。"""
        ...


class StretchRouter(RoutingStrategy):
    """基于引脚位移的增量拉伸路由器。

    - 直线：两端按各自引脚位移移动端点
    - L型折线：两端移动端点，拐点按加权比例调整
    - 超阈值：标记断线，在版图中放置X标记
    """

    MAX_STRETCH_UM = 100.0  # 单端最大拉伸阈值 (um)

    def maintain(
        self,
        layout: db.Layout,
        cell: db.Cell,
        old_pins: dict[str, db.DPoint],
        new_pins: dict[str, db.DPoint],
        threshold_dbu: float = 100000,  # 100um in DBU
    ) -> RoutingResult:
        """兼容旧接口的简单实现。"""
        threshold_um = threshold_dbu * layout.dbu
        modified = []
        needs_fix = []

        for pin_name, old_pos in old_pins.items():
            if pin_name not in new_pins:
                needs_fix.append(pin_name)
                continue
            new_pos = new_pins[pin_name]
            dist = math.sqrt(
                (new_pos.x - old_pos.x) ** 2 + (new_pos.y - old_pos.y) ** 2
            ) * layout.dbu

            if dist < 0.01:
                continue
            if dist <= threshold_um:
                modified.append(pin_name)
            else:
                needs_fix.append(pin_name)

        return RoutingResult(
            success=len(needs_fix) == 0,
            modified_paths=modified,
            needs_manual_fix=needs_fix,
            message=f"拉伸{len(modified)}根线，{len(needs_fix)}根需人工修复",
        )

    def stretch_connections(
        self,
        layout: db.Layout,
        cell: db.Cell,
        connections: List[Connection],
        old_pins: Dict[str, PinState],
        new_pins: Dict[str, PinState],
        threshold_um: float = 100.0,
    ) -> StretchResult:
        """执行连线拉伸。

        Args:
            layout: KLayout Layout对象
            cell: 顶层Cell
            connections: 连线列表
            old_pins: {ref.pin_name: PinState} 修改前
            new_pins: {ref.pin_name: PinState} 修改后
            threshold_um: 拉伸阈值 (um)

        Returns:
            StretchResult
        """
        stretched = []
        broken = []

        for conn in connections:
            key_a = conn.pin_a.key
            key_b = conn.pin_b.key

            # 获取两端引脚位移
            disp_a = (0.0, 0.0)
            disp_b = (0.0, 0.0)

            if key_a in old_pins and key_a in new_pins:
                disp_a = old_pins[key_a].displacement(new_pins[key_a])
            if key_b in old_pins and key_b in new_pins:
                disp_b = old_pins[key_b].displacement(new_pins[key_b])

            # 判断是否超出阈值
            max_disp = max(
                math.sqrt(disp_a[0] ** 2 + disp_a[1] ** 2),
                math.sqrt(disp_b[0] ** 2 + disp_b[1] ** 2),
            )

            if max_disp > threshold_um:
                broken.append(conn.net_name)
                self._mark_broken(layout, cell, conn, new_pins)
                continue

            # 执行拉伸
            for wire in conn.wires:
                self._stretch_wire(layout, cell, wire, disp_a, disp_b)

            stretched.append(conn.net_name)

        return StretchResult(
            stretched=stretched,
            broken=broken,
            total=len(connections),
        )

    def _stretch_wire(
        self,
        layout: db.Layout,
        cell: db.Cell,
        wire: WireSegment,
        disp_a: Tuple[float, float],
        disp_b: Tuple[float, float],
    ) -> None:
        """拉伸单条走线。

        策略：
        - 直线：两端按各自引脚位移移动端点
        - L型：两端移动端点，拐点按加权比例调整
        - 复杂折线：两端移动，中间等比插值
        """
        old_points = wire.points
        n = len(old_points)
        new_points = []

        for i, (x, y) in enumerate(old_points):
            if n == 2:
                # 直线
                dx, dy = disp_a if i == 0 else disp_b
            elif n == 3:
                # L型
                if i == 0:
                    dx, dy = disp_a
                elif i == 2:
                    dx, dy = disp_b
                else:
                    # 拐点：按距离加权
                    p0 = old_points[0]
                    p2 = old_points[2]
                    total = math.sqrt(
                        (p2[0] - p0[0]) ** 2 + (p2[1] - p0[1]) ** 2
                    )
                    if total > 0:
                        ratio = math.sqrt(
                            (x - p0[0]) ** 2 + (y - p0[1]) ** 2
                        ) / total
                    else:
                        ratio = 0.5
                    dx = disp_a[0] * (1 - ratio) + disp_b[0] * ratio
                    dy = disp_a[1] * (1 - ratio) + disp_b[1] * ratio
            else:
                # 复杂折线：线性插值
                if i == 0:
                    dx, dy = disp_a
                elif i == n - 1:
                    dx, dy = disp_b
                else:
                    t = i / (n - 1)
                    dx = disp_a[0] * (1 - t) + disp_b[0] * t
                    dy = disp_a[1] * (1 - t) + disp_b[1] * t

            new_points.append((x + dx, y + dy))

        # 先删除旧走线几何，再绘制新走线
        self._erase_wire(layout, cell, wire, old_points)
        self._draw_wire(layout, cell, wire, new_points)

    def _erase_wire(
        self,
        layout: db.Layout,
        cell: db.Cell,
        wire: WireSegment,
        points: List[Tuple[float, float]],
    ) -> None:
        """删除旧走线几何：用覆盖box从对应layer的Region中擦除。"""
        layer_idx = layout.layer(*wire.layer)
        dbu = layout.dbu
        half_w = wire.width / 2.0

        # 收集所有需擦除的box（与_draw_wire同样的几何逻辑）
        erase_region = db.Region()
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]

            x1d, y1d = int(x1 / dbu), int(y1 / dbu)
            x2d, y2d = int(x2 / dbu), int(y2 / dbu)
            hwd = int(half_w / dbu)

            if abs(y1d - y2d) < max(1, hwd // 10):
                # 水平段
                erase_region += db.Region(db.Box(min(x1d, x2d), y1d - hwd, max(x1d, x2d), y1d + hwd))
            elif abs(x1d - x2d) < max(1, hwd // 10):
                # 垂直段
                erase_region += db.Region(db.Box(x1d - hwd, min(y1d, y2d), x1d + hwd, max(y1d, y2d)))
            else:
                # 斜线：用Path的bounding box近似
                path = db.Path(
                    [db.Point(x1d, y1d), db.Point(x2d, y2d)],
                    hwd * 2,
                )
                erase_region += db.Region(path.bbox())

        # 从cell的shapes中擦除
        if not erase_region.is_empty():
            shapes = cell.shapes(layer_idx)
            old_region = db.Region(shapes)
            new_region = old_region - erase_region
            shapes.clear()
            shapes.insert(new_region)

    def _draw_wire(
        self,
        layout: db.Layout,
        cell: db.Cell,
        wire: WireSegment,
        points: List[Tuple[float, float]],
    ) -> None:
        """绘制走线几何到cell。"""
        layer_idx = layout.layer(*wire.layer)
        dbu = layout.dbu
        half_w = wire.width / 2.0

        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]

            # um → dbu
            x1d, y1d = int(x1 / dbu), int(y1 / dbu)
            x2d, y2d = int(x2 / dbu), int(y2 / dbu)
            hwd = int(half_w / dbu)

            # 判断水平/垂直
            if abs(y1d - y2d) < max(1, hwd // 10):
                # 水平段
                box = db.Box(min(x1d, x2d), y1d - hwd, max(x1d, x2d), y1d + hwd)
                cell.shapes(layer_idx).insert(box)
            elif abs(x1d - x2d) < max(1, hwd // 10):
                # 垂直段
                box = db.Box(x1d - hwd, min(y1d, y2d), x1d + hwd, max(y1d, y2d))
                cell.shapes(layer_idx).insert(box)
            else:
                # 斜线：用Path
                path = db.Path(
                    [db.Point(x1d, y1d), db.Point(x2d, y2d)],
                    hwd * 2,
                )
                cell.shapes(layer_idx).insert(path)

    def _mark_broken(
        self,
        layout: db.Layout,
        cell: db.Cell,
        conn: Connection,
        new_pins: Dict[str, PinState],
    ) -> None:
        """在断线位置放置X标记。"""
        marker_layer = layout.layer(*BasePCell.BROKEN_MARKER_LAYER)  # 标记层

        # 取两引脚新位置的中点
        key_a = conn.pin_a.key
        key_b = conn.pin_b.key
        pa = new_pins.get(key_a, conn.pin_a)
        pb = new_pins.get(key_b, conn.pin_b)

        mid_x = (pa.x + pb.x) / 2.0
        mid_y = (pa.y + pb.y) / 2.0

        dbu = layout.dbu
        size = int(5.0 / dbu)   # 5um标记
        third = max(1, size // 3)
        cx = int(mid_x / dbu)
        cy = int(mid_y / dbu)

        # 画X标记
        cell.shapes(marker_layer).insert(
            db.Box(cx - size, cy - third, cx + size, cy + third)
        )
        cell.shapes(marker_layer).insert(
            db.Box(cx - third, cy - size, cx + third, cy + size)
        )
        # 标注网络名
        cell.shapes(marker_layer).insert(
            db.Text(f"BROKEN:{conn.net_name}", db.Trans(db.Point(cx, cy + size + int(2 / dbu))))
        )

        logger.warning(f"断线标记: {conn.net_name} @ ({mid_x:.1f}, {mid_y:.1f})")
