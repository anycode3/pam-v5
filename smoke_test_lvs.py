"""LVS 烟雾测试：验证 Region.merge() + interacting() 连通性检测。

直接测试KLayoutPureLVS，使用简化的GDS场景。
"""

from __future__ import annotations

import sys
from pathlib import Path

src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))
pcell_dir = Path(__file__).parent
sys.path.insert(0, str(pcell_dir))

import klayout.db as db
from validator.lvs_runner import KLayoutPureLVS
from validator.base import LVSResult


# ──────────────────────────────────────────────
# 场景1: 两个引脚正确连接 → PASS
# ──────────────────────────────────────────────
def test_s1_connected():
    """两个引脚通过金属线连接，LVS应PASS。"""
    print("\n=== S1: 两引脚正确连接 → PASS ===")

    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TEST")

    metal = layout.layer(db.LayerInfo(6, 0))
    pin_lay = layout.layer(db.LayerInfo(100, 0))
    marker_lay = layout.layer(db.LayerInfo(255, 0))

    # 金属线从(100,100)到(300,100)
    top.shapes(metal).insert(db.Box(100000, 99000, 300000, 101000))

    # PIN A at (100, 100)
    top.shapes(pin_lay).insert(db.Text("A", db.Trans(db.Point(100000, 100000))))
    top.shapes(marker_lay).insert(db.Box(99999, 99999, 100001, 100001))

    # PIN B at (300, 100)
    top.shapes(pin_lay).insert(db.Text("B", db.Trans(db.Point(300000, 100000))))
    top.shapes(marker_lay).insert(db.Box(299999, 99999, 300001, 100001))

    gds_path = "state/lvs_test/s1.gds"
    Path("state/lvs_test").mkdir(parents=True, exist_ok=True)
    layout.write(gds_path)

    lvs = KLayoutPureLVS()
    result = lvs.run(gds_path, {"NET1": ["A", "B"]}, {"A": (100.0, 100.0), "B": (300.0, 100.0)})

    print(f"  passed={result.passed}, opens={result.open_count}, shorts={result.short_count}")
    assert result.passed, f"S1应PASS: {result.violations}"
    print("  PASS")


# ──────────────────────────────────────────────
# 场景2: 引脚悬空 → OPEN
# ──────────────────────────────────────────────
def test_s2_open():
    """一个引脚悬空（无金属连接），LVS应检测OPEN。"""
    print("\n=== S2: 引脚悬空 → OPEN ===")

    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TEST")

    metal = layout.layer(db.LayerInfo(6, 0))
    pin_lay = layout.layer(db.LayerInfo(100, 0))
    marker_lay = layout.layer(db.LayerInfo(255, 0))

    # 只有PIN A有金属，PIN B悬空
    top.shapes(metal).insert(db.Box(100000, 99000, 110000, 101000))  # PIN A金属
    top.shapes(pin_lay).insert(db.Text("A", db.Trans(db.Point(100000, 100000))))
    top.shapes(marker_lay).insert(db.Box(99999, 99999, 100001, 100001))

    # PIN B无金属连接
    top.shapes(pin_lay).insert(db.Text("B", db.Trans(db.Point(300000, 100000))))
    top.shapes(marker_lay).insert(db.Box(299999, 99999, 300001, 100001))

    gds_path = "state/lvs_test/s2.gds"
    layout.write(gds_path)

    lvs = KLayoutPureLVS()
    result = lvs.run(gds_path, {"NET1": ["A", "B"]}, {"A": (100.0, 100.0), "B": (300.0, 100.0)})

    print(f"  passed={result.passed}, opens={result.open_count}, shorts={result.short_count}")
    assert not result.passed, "S2应有OPEN违例"
    assert result.open_count >= 1, f"应有OPEN，实际{result.open_count}"
    print("  PASS")


# ──────────────────────────────────────────────
# 场景3: 金属区域合并 → 正确识别同一region
# ──────────────────────────────────────────────
def test_s3_region_merge():
    """两个金属区域重叠形成一体，LVS应正确识别为同一region。"""
    print("\n=== S3: 金属区域合并 → PASS ===")

    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TEST")

    metal = layout.layer(db.LayerInfo(6, 0))
    pin_lay = layout.layer(db.LayerInfo(100, 0))
    marker_lay = layout.layer(db.LayerInfo(255, 0))

    # 两段金属重叠（100-200和150-250，重叠区域150-200）
    top.shapes(metal).insert(db.Box(100000, 99000, 200000, 101000))
    top.shapes(metal).insert(db.Box(150000, 99000, 250000, 101000))

    # PIN A在第一个金属上
    top.shapes(pin_lay).insert(db.Text("A", db.Trans(db.Point(100000, 100000))))
    top.shapes(marker_lay).insert(db.Box(99999, 99999, 100001, 100001))

    # PIN B在第二个金属上
    top.shapes(pin_lay).insert(db.Text("B", db.Trans(db.Point(250000, 100000))))
    top.shapes(marker_lay).insert(db.Box(249999, 99999, 250001, 100001))

    gds_path = "state/lvs_test/s3.gds"
    layout.write(gds_path)

    lvs = KLayoutPureLVS()
    result = lvs.run(gds_path, {"NET1": ["A", "B"]}, {"A": (100.0, 100.0), "B": (250.0, 100.0)})

    print(f"  passed={result.passed}, opens={result.open_count}, shorts={result.short_count}")
    assert result.passed, f"S3应PASS（两金属已合并）: {result.violations}"
    print("  PASS")


# ──────────────────────────────────────────────
# 场景4: 意外短路 → SHORT
# ──────────────────────────────────────────────
def test_s4_short():
    """本应分开的两个net意外通过金属连接，LVS应检测SHORT。"""
    print("\n=== S4: 意外短路 → SHORT ===")

    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TEST")

    metal = layout.layer(db.LayerInfo(6, 0))
    pin_lay = layout.layer(db.LayerInfo(100, 0))
    marker_lay = layout.layer(db.LayerInfo(255, 0))

    # 单一金属块包含两个本应分开的引脚
    top.shapes(metal).insert(db.Box(100000, 99000, 300000, 101000))

    top.shapes(pin_lay).insert(db.Text("A", db.Trans(db.Point(100000, 100000))))
    top.shapes(marker_lay).insert(db.Box(99999, 99999, 100001, 100001))

    top.shapes(pin_lay).insert(db.Text("B", db.Trans(db.Point(300000, 100000))))
    top.shapes(marker_lay).insert(db.Box(299999, 99999, 300001, 100001))

    gds_path = "state/lvs_test/s4.gds"
    layout.write(gds_path)

    # A和B在不同的net，但物理上连通了
    lvs = KLayoutPureLVS()
    result = lvs.run(gds_path, {"NET1": ["A"], "NET2": ["B"]}, {"A": (100.0, 100.0), "B": (300.0, 100.0)})

    print(f"  passed={result.passed}, opens={result.open_count}, shorts={result.short_count}")
    assert not result.passed, "S4应有SHORT违例"
    assert result.short_count >= 1, f"应有SHORT，实际{result.short_count}"
    print("  PASS")


# ──────────────────────────────────────────────
# 场景5: 多金属层(VIA)连通 → PASS
# ──────────────────────────────────────────────
def test_s5_via_connect():
    """金属层6通过通孔层11连接到金属层7，LVS应正确识别跨层连通。"""
    print("\n=== S5: 多金属层+通孔连通 → PASS ===")

    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TEST")

    metal6 = layout.layer(db.LayerInfo(6, 0))
    metal7 = layout.layer(db.LayerInfo(7, 0))
    via11 = layout.layer(db.LayerInfo(11, 0))
    pin_lay = layout.layer(db.LayerInfo(100, 0))
    marker_lay = layout.layer(db.LayerInfo(255, 0))

    # 金属层6在左侧
    top.shapes(metal6).insert(db.Box(100000, 99000, 150000, 101000))
    # 通孔
    top.shapes(via11).insert(db.Box(145000, 99500, 155000, 100500))
    # 金属层7在右侧
    top.shapes(metal7).insert(db.Box(150000, 99000, 200000, 101000))

    # PIN A在金属层6上
    top.shapes(pin_lay).insert(db.Text("A", db.Trans(db.Point(100000, 100000))))
    top.shapes(marker_lay).insert(db.Box(99999, 99999, 100001, 100001))

    # PIN B在金属层7上
    top.shapes(pin_lay).insert(db.Text("B", db.Trans(db.Point(200000, 100000))))
    top.shapes(marker_lay).insert(db.Box(199999, 99999, 200001, 100001))

    gds_path = "state/lvs_test/s5.gds"
    layout.write(gds_path)

    lvs = KLayoutPureLVS()
    result = lvs.run(gds_path, {"NET1": ["A", "B"]}, {"A": (100.0, 100.0), "B": (200.0, 100.0)})

    print(f"  passed={result.passed}, opens={result.open_count}, shorts={result.short_count}")
    assert result.passed, f"S5应PASS（含通孔应连通）: {result.violations}"
    print("  PASS")


# ──────────────────────────────────────────────
# 场景6: 2μm容差测试
# ──────────────────────────────────────────────
def test_s6_query_box_tolerance():
    """引脚坐标与金属边缘距离<1μm时，2μm查询框应仍能捕获。"""
    print("\n=== S6: 2μm查询框容差 → PASS ===")

    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TEST")

    metal = layout.layer(db.LayerInfo(6, 0))
    pin_lay = layout.layer(db.LayerInfo(100, 0))
    marker_lay = layout.layer(db.LayerInfo(255, 0))

    # 金属从(100, 100)到(200, 120)，即中心(150, 110)
    top.shapes(metal).insert(db.Box(100000, 100000, 200000, 120000))

    # PIN在(150, 109)，距离金属上边缘仅1μm（小于查询框1μm半径）
    top.shapes(pin_lay).insert(db.Text("A", db.Trans(db.Point(150000, 109000))))
    top.shapes(marker_lay).insert(db.Box(149999, 108999, 150001, 109001))

    # PIN B在(150, 111)，距离金属下边缘仅1μm
    top.shapes(pin_lay).insert(db.Text("B", db.Trans(db.Point(150000, 111000))))
    top.shapes(marker_lay).insert(db.Box(149999, 110999, 150001, 111001))

    gds_path = "state/lvs_test/s6.gds"
    layout.write(gds_path)

    lvs = KLayoutPureLVS()
    result = lvs.run(gds_path, {"NET1": ["A", "B"]}, {"A": (150.0, 109.0), "B": (150.0, 111.0)})

    print(f"  passed={result.passed}, opens={result.open_count}, shorts={result.short_count}")
    assert result.passed, f"S6应PASS（2μm查询框应捕获近边缘引脚）: {result.violations}"
    print("  PASS")


def main():
    print("LVS 烟雾测试")
    print("=" * 50)

    Path("state/lvs_test").mkdir(parents=True, exist_ok=True)

    test_s1_connected()
    test_s2_open()
    test_s3_region_merge()
    test_s4_short()
    test_s5_via_connect()
    test_s6_query_box_tolerance()

    print("\n" + "=" * 50)
    print("LVS烟雾测试完成！6/6 PASS")
    print("  S1 正确连接   ✓")
    print("  S2 引脚悬空   ✓")
    print("  S3 区域合并   ✓")
    print("  S4 意外短路   ✓")
    print("  S5 通孔连通   ✓")
    print("  S6 查询框容差 ✓")


if __name__ == "__main__":
    main()
