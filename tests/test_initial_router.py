"""initial_router 单元测试。"""

import pytest
import klayout.db as db

from src.routing.initial_router import (
    route_connection,
    draw_wire_segments,
    erase_wire_segments,
    InitialRouter,
    DEFAULT_WIRE_LAYER,
    DEFAULT_WIRE_WIDTH,
)
from src.routing.types import PinState, WireSegment


class TestRouteConnection:
    """route_connection 函数。"""

    def test_straight_horizontal(self):
        pa = PinState(name="PI", ref="C1", x=0.0, y=10.0)
        pb = PinState(name="P1", ref="L1", x=100.0, y=10.0)
        wires = route_connection(pa, pb)
        assert len(wires) == 1
        assert wires[0].is_straight
        assert wires[0].points == [(0.0, 10.0), (100.0, 10.0)]

    def test_straight_vertical(self):
        pa = PinState(name="PI", ref="C1", x=50.0, y=0.0)
        pb = PinState(name="P1", ref="L1", x=50.0, y=100.0)
        wires = route_connection(pa, pb)
        assert len(wires) == 1
        assert wires[0].is_straight

    def test_l_shape(self):
        pa = PinState(name="PI", ref="C1", x=0.0, y=0.0)
        pb = PinState(name="P1", ref="L1", x=100.0, y=50.0)
        wires = route_connection(pa, pb)
        assert len(wires) == 1
        assert wires[0].is_l_shape
        # L 型：先水平后垂直
        assert wires[0].points[0] == (0.0, 0.0)
        assert wires[0].points[-1] == (100.0, 50.0)

    def test_custom_wire_width(self):
        pa = PinState(name="PI", ref="C1", x=0.0, y=0.0)
        pb = PinState(name="P1", ref="L1", x=100.0, y=0.0)
        wires = route_connection(pa, pb, wire_width=20.0)
        assert wires[0].width == 20.0

    def test_default_wire_layer(self):
        pa = PinState(name="PI", ref="C1", x=0.0, y=0.0)
        pb = PinState(name="P1", ref="L1", x=100.0, y=0.0)
        wires = route_connection(pa, pb)
        assert wires[0].layer == DEFAULT_WIRE_LAYER


class TestDrawAndEraseWireSegments:
    """draw_wire_segments 和 erase_wire_segments。"""

    def _create_layout(self):
        layout = db.Layout()
        layout.dbu = 0.001
        top = layout.create_cell("TOP")
        return layout, top

    def test_draw_horizontal_wire(self):
        layout, top = self._create_layout()
        wire = WireSegment(
            layer=(6, 0),
            points=[(0.0, 10.0), (100.0, 10.0)],
            width=10.0,
        )
        draw_wire_segments(top, layout, [wire])

        layer_idx = layout.layer(6, 0)
        region = db.Region(top.shapes(layer_idx))
        assert not region.is_empty()

    def test_draw_l_shape_wire(self):
        layout, top = self._create_layout()
        wire = WireSegment(
            layer=(6, 0),
            points=[(0.0, 0.0), (100.0, 0.0), (100.0, 50.0)],
            width=10.0,
        )
        draw_wire_segments(top, layout, [wire])

        layer_idx = layout.layer(6, 0)
        region = db.Region(top.shapes(layer_idx))
        assert not region.is_empty()

    def test_erase_drawn_wire(self):
        layout, top = self._create_layout()
        wire = WireSegment(
            layer=(6, 0),
            points=[(0.0, 10.0), (100.0, 10.0)],
            width=10.0,
        )

        # 画然后擦
        draw_wire_segments(top, layout, [wire])
        erase_wire_segments(top, layout, [wire])

        layer_idx = layout.layer(6, 0)
        region = db.Region(top.shapes(layer_idx))
        assert region.is_empty()

    def test_erase_partial(self):
        """擦除部分形状，保留其他。"""
        layout, top = self._create_layout()

        wire1 = WireSegment(
            layer=(6, 0),
            points=[(0.0, 10.0), (100.0, 10.0)],
            width=10.0,
        )
        wire2 = WireSegment(
            layer=(6, 0),
            points=[(200.0, 10.0), (300.0, 10.0)],
            width=10.0,
        )

        draw_wire_segments(top, layout, [wire1, wire2])

        # 只擦除 wire1
        erase_wire_segments(top, layout, [wire1])

        layer_idx = layout.layer(6, 0)
        region = db.Region(top.shapes(layer_idx))
        # wire2 应该还在
        assert not region.is_empty()


class TestInitialRouter:
    """InitialRouter 类。"""

    def _create_layout_with_devices(self):
        """创建带子 cell 的 layout 供 route_all 测试。

        需要子 cell 有 PIN marker 和 PCell 兼容名称。
        """
        layout = db.Layout()
        layout.dbu = 0.001
        top = layout.create_cell("TOP")

        # 创建 C1 子 cell（含 PIN marker）
        c1 = layout.create_cell("C1_CAP_MIM")
        marker_layer = layout.layer(db.LayerInfo(255, 0))
        c1.shapes(marker_layer).insert(db.Text("PI", db.Trans(db.Point(50000, 30000))))
        c1.shapes(marker_layer).insert(db.Text("NIN", db.Trans(db.Point(50000, 5000))))
        top.insert(db.CellInstArray(c1, db.Trans(0, 0)))

        return layout, top

    def test_route_affected_nets_empty(self):
        """无受影响网络返回空。"""
        layout, top = self._create_layout_with_devices()
        router = InitialRouter()

        from src.parser.kicad_netlist import Net
        nets = [Net(name="NET1", nodes=[("C1", "PI"), ("C1", "NIN")])]

        result = router.route_affected_nets(
            layout=layout,
            top_cell=top,
            nets=nets,
            changed_refs=["C2"],  # 不存在的 ref
            ref_to_pcell={"C1": "CAP_MIM"},
            ref_to_params={"C1": {"length": 50, "width": 30}},
        )
        assert result == {}
