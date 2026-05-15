"""pin_extractor 单元测试。

使用 KLayout API 创建合成 GDS 来测试引脚提取逻辑。
"""

import pytest
import klayout.db as db

from src.routing.pin_extractor import (
    extract_pin_positions,
    extract_pin_layers,
    _extract_ref_from_cell_name,
    PIN_MARKER_LAYER,
)


def _create_test_layout():
    """创建带有子 cell + PIN marker 的测试 layout。

    结构：
    - top_cell: "TOP"
    - sub_cell: "C1_CAP_MIM"（含 PIN marker 文本 "PI" 和 "NIN"）
    - instance: C1 放置在 (100, 200) 位置
    """
    layout = db.Layout()
    layout.dbu = 0.001  # 1nm DBU

    top = layout.create_cell("TOP")

    # 创建子 cell
    sub = layout.create_cell("C1_CAP_MIM")
    marker_layer = layout.layer(db.LayerInfo(*PIN_MARKER_LAYER))
    metal_layer = layout.layer(db.LayerInfo(6, 0))

    # 放置 PIN marker 文本（本地坐标）
    # PI 在本地 (50, 30), NIN 在本地 (50, 5)
    sub.shapes(marker_layer).insert(db.Text("PI", db.Trans(db.Point(50000, 30000))))
    sub.shapes(marker_layer).insert(db.Text("NIN", db.Trans(db.Point(50000, 5000))))

    # 在 PIN 位置放置金属层形状（供 extract_pin_layers 测试）
    sub.shapes(metal_layer).insert(db.Box(49000, 29000, 51000, 31000))  # PI 附近
    sub.shapes(metal_layer).insert(db.Box(49000, 4000, 51000, 6000))    # NIN 附近

    # 创建 instance，位移 (100um, 200um) = (100000, 200000) DBU
    inst = top.insert(db.CellInstArray(sub, db.Trans(100000, 200000)))

    return layout, top


class TestExtractRefFromCellName:
    """从 cell 名提取 ref。"""

    def test_standard_format(self):
        assert _extract_ref_from_cell_name("C1_CAP_MIM") == "C1"

    def test_transmission_line(self):
        assert _extract_ref_from_cell_name("TL1_TL_MICROSTRIP") == "TL1"

    def test_no_underscore(self):
        assert _extract_ref_from_cell_name("L1") == "L1"

    def test_empty_string(self):
        assert _extract_ref_from_cell_name("") is None


class TestExtractPinPositions:
    """从 GDS 提取引脚全局坐标。"""

    def test_basic_extraction(self):
        layout, top = _create_test_layout()
        result = extract_pin_positions(layout, top)

        assert "C1" in result
        assert "PI" in result["C1"]
        assert "NIN" in result["C1"]

    def test_global_coordinates(self):
        """验证本地坐标 + instance 位移 = 全局坐标。"""
        layout, top = _create_test_layout()
        result = extract_pin_positions(layout, top)

        # 本地 PI=(50,30) + 位移(100,200) = 全局 (150,230)
        pi_x, pi_y = result["C1"]["PI"]
        assert abs(pi_x - 150.0) < 0.1
        assert abs(pi_y - 230.0) < 0.1

        # 本地 NIN=(50,5) + 位移(100,200) = 全局 (150,205)
        nin_x, nin_y = result["C1"]["NIN"]
        assert abs(nin_x - 150.0) < 0.1
        assert abs(nin_y - 205.0) < 0.1

    def test_empty_top_cell(self):
        """top cell 无 instance。"""
        layout = db.Layout()
        layout.dbu = 0.001
        top = layout.create_cell("TOP")
        result = extract_pin_positions(layout, top)
        assert result == {}

    def test_no_pin_markers(self):
        """子 cell 无 PIN marker。"""
        layout = db.Layout()
        layout.dbu = 0.001
        top = layout.create_cell("TOP")
        sub = layout.create_cell("R1_RESISTOR")
        # 无 PIN marker
        top.insert(db.CellInstArray(sub, db.Trans(0, 0)))
        result = extract_pin_positions(layout, top)
        assert result == {}


class TestExtractPinLayers:
    """从 GDS 提取引脚层信息。"""

    def test_basic_extraction(self):
        layout, top = _create_test_layout()
        result = extract_pin_layers(layout, top)

        assert "C1" in result
        assert "PI" in result["C1"]
        assert "NIN" in result["C1"]
        # 金属层是 (6, 0)
        assert result["C1"]["PI"] == (6, 0)
        assert result["C1"]["NIN"] == (6, 0)
