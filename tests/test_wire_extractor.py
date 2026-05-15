"""wire_extractor 单元测试。

使用 KLayout API 创建合成 GDS 来测试连线提取和擦除逻辑。
"""

import pytest
import klayout.db as db

from src.routing.wire_extractor import (
    extract_wires_from_gds,
    erase_wires_from_top_cell,
    _find_nearest_net,
)
from src.routing.pin_extractor import PIN_MARKER_LAYER
from src.routing.types import WireSegment


def _create_layout_with_wires():
    """创建带有子 cell（含 PIN marker）+ top cell 走线的测试 layout。

    结构：
    - top_cell: "TOP"
    - sub_cell: "C1_CAP_MIM" with pins PI(50,30), NIN(50,5)
    - sub_cell: "L1_IND_SPIRAL" with pins P1(0,0), P2(100,0)
    - C1 instance at (0, 0)
    - L1 instance at (200, 0)
    - Wire on top_cell layer 6: box connecting C1.PI to L1.P1
    """
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TOP")

    # 子 cell C1
    c1 = layout.create_cell("C1_CAP_MIM")
    marker_layer = layout.layer(db.LayerInfo(*PIN_MARKER_LAYER))
    c1.shapes(marker_layer).insert(db.Text("PI", db.Trans(db.Point(50000, 30000))))
    c1.shapes(marker_layer).insert(db.Text("NIN", db.Trans(db.Point(50000, 5000))))
    top.insert(db.CellInstArray(c1, db.Trans(0, 0)))

    # 子 cell L1
    l1 = layout.create_cell("L1_IND_SPIRAL")
    l1.shapes(marker_layer).insert(db.Text("P1", db.Trans(db.Point(0, 0))))
    l1.shapes(marker_layer).insert(db.Text("P2", db.Trans(db.Point(100000, 0))))
    top.insert(db.CellInstArray(l1, db.Trans(200000, 0)))

    # top cell 上的走线：C1.PI(50,30) → L1.P1(200,0)
    metal_layer = layout.layer(db.LayerInfo(6, 0))
    # 水平段：从 (50,30) 到 (200,30)
    top.shapes(metal_layer).insert(db.Box(50000, 25000, 200000, 35000))

    return layout, top


class TestExtractWiresFromGDS:
    """从 GDS 提取连线。"""

    def test_extract_with_nets(self):
        layout, top = _create_layout_with_wires()

        # 模拟网表网络
        from src.parser.kicad_netlist import Net
        nets = [
            Net(name="NET1", nodes=[("C1", "PI"), ("L1", "P1")]),
        ]

        result = extract_wires_from_gds(layout, top, nets)
        # 应该能提取到连线
        assert len(result) > 0

    def test_empty_top_cell(self):
        layout = db.Layout()
        layout.dbu = 0.001
        top = layout.create_cell("TOP")
        result = extract_wires_from_gds(layout, top, [])
        assert result == {}

    def test_excluded_layers_ignored(self):
        """PIN marker 层和 PIN 层的形状不应被当作连线提取。"""
        layout, top = _create_layout_with_wires()

        # 在 top cell 的 PIN 层 (100/0) 上添加形状
        pin_layer = layout.layer(db.LayerInfo(100, 0))
        top.shapes(pin_layer).insert(db.Box(0, 0, 10000, 10000))

        from src.parser.kicad_netlist import Net
        nets = [Net(name="NET1", nodes=[("C1", "PI")])]

        result = extract_wires_from_gds(layout, top, nets)
        # PIN 层的形状不应被提取为连线
        for net_name, wires in result.items():
            for w in wires:
                assert w.layer[0] != 100


class TestEraseWiresFromTopCell:
    """擦除指定网络的连线。"""

    def test_erase_specific_net(self):
        layout, top = _create_layout_with_wires()

        from src.parser.kicad_netlist import Net
        nets = [Net(name="NET1", nodes=[("C1", "PI"), ("L1", "P1")])]

        old_wires = extract_wires_from_gds(layout, top, nets)
        metal_layer_idx = layout.layer(db.LayerInfo(6, 0))

        # 擦除前有形状
        region_before = db.Region(top.shapes(metal_layer_idx))
        assert not region_before.is_empty()

        # 执行擦除
        erase_wires_from_top_cell(layout, top, ["NET1"], old_wires)

        # 擦除后应该为空（或接近空）
        region_after = db.Region(top.shapes(metal_layer_idx))
        assert region_after.is_empty() or region_before.area() > region_after.area()

    def test_erase_nonexistent_net(self):
        """擦除不存在的网络不应出错。"""
        layout, top = _create_layout_with_wires()
        wires = {"NONEXISTENT": [WireSegment(layer=(6, 0), points=[(0, 0), (100, 0)], width=10.0)]}
        # 不应抛出异常
        erase_wires_from_top_cell(layout, top, ["NONEXISTENT"], wires)


class TestFindNearestNet:
    """为无引脚关联的 shape 找最近网络。"""

    def test_nearby_pin(self):
        layout = db.Layout()
        layout.dbu = 0.001

        box = db.Box(48000, 28000, 52000, 32000)  # 中心约 (50, 30)
        pin_positions = {"C1": {"PI": (50.0, 30.0)}}
        pin_to_net = {("C1", "PI"): "NET1"}

        result = _find_nearest_net(box, pin_positions, pin_to_net, 0.001)
        assert result == "NET1"

    def test_far_away_pin(self):
        """距离超过阈值应返回 None。"""
        layout = db.Layout()
        layout.dbu = 0.001

        box = db.Box(1000000, 1000000, 1010000, 1010000)  # 中心约 (1005, 1005)
        pin_positions = {"C1": {"PI": (50.0, 30.0)}}
        pin_to_net = {("C1", "PI"): "NET1"}

        result = _find_nearest_net(box, pin_positions, pin_to_net, 0.001)
        assert result is None
