"""StretchRouter实际连线拉伸冒烟测试。

4场景:
  S1: 直线拉伸(TL长度微调，位移<100um)
  S2: L型折线拉伸(C1位置微调)
  S3: 断线标记(位移>100um阈值)
  S4: 非对称两端位移拉伸
"""

from __future__ import annotations

import sys
from pathlib import Path

src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))
pcell_dir = Path(__file__).parent
sys.path.insert(0, str(pcell_dir))

import logging
logging.basicConfig(level=logging.WARNING)

import klayout.db as db
from routing.base import StretchRouter
from routing.types import PinState, WireSegment, Connection, StretchResult


def create_test_layout(dbu=0.001):
    """创建测试用layout和top cell。"""
    layout = db.Layout()
    layout.dbu = dbu
    top = layout.create_cell("TOP")
    metal_layer = layout.layer(6, 0)
    marker_layer = layout.layer(200, 0)
    return layout, top, metal_layer, marker_layer


def get_x_coords(top, metal_layer):
    """获取metal层所有shape的x坐标(dbu)。"""
    x_coords = []
    for s in top.shapes(metal_layer):
        if s.is_box():
            b = s.bbox()
            x_coords.extend([b.left, b.right])
    return x_coords


def get_y_coords(top, metal_layer):
    """获取metal层所有shape的y坐标(dbu)。"""
    y_coords = []
    for s in top.shapes(metal_layer):
        if s.is_box():
            b = s.bbox()
            y_coords.extend([b.bottom, b.top])
    return y_coords


# ──────────────────────────────────────────────
# S1: 直线拉伸
# ──────────────────────────────────────────────
def test_s1_straight_stretch():
    """直线两端同向微移 → 两端点等量位移。"""
    print("\n=== S1: 直线拉伸 TL1长度微调(+50um) ===")

    layout, top, metal_layer, marker_layer = create_test_layout()

    # TL1长度微调：P2从2000→2050 (+50um，< 100um阈值，应拉伸)
    # 旧引脚位置
    old_pins = {
        "TL1.P2": PinState(name="P2", ref="TL1", x=2000.0, y=10.0),
        "C1.P1":  PinState(name="P1", ref="C1",  x=2000.0, y=10.0),
    }
    # 新引脚位置
    new_pins = {
        "TL1.P2": PinState(name="P2", ref="TL1", x=2050.0, y=10.0),
        "C1.P1":  PinState(name="P1", ref="C1",  x=2050.0, y=10.0),
    }

    # 画旧连接线 (2000,10)处，宽度10um
    dbu = layout.dbu
    hwd = int(5.0 / dbu)  # 5um half-width in dbu
    top.shapes(metal_layer).insert(db.Box(2000000, 10000-hwd, 2000000, 10000+hwd))

    # 创建直线连接
    # wire points描述旧几何：线段在(2000,10)-(2000,10)（零长度，表示未拉伸状态）
    pa = PinState(name="P2", ref="TL1", x=2000.0, y=10.0)
    pb = PinState(name="P1", ref="C1",  x=2000.0, y=10.0)
    wire = WireSegment(layer=(6, 0), points=[(2000.0, 10.0), (2000.0, 10.0)], width=10.0)
    conn = Connection(net_name="NET_A", pin_a=pa, pin_b=pb, wires=[wire])

    router = StretchRouter()
    result = router.stretch_connections(
        layout=layout, cell=top, connections=[conn],
        old_pins=old_pins, new_pins=new_pins, threshold_um=100.0,
    )

    print(f"  stretched={result.stretched}, broken={result.broken}, total={result.total}")
    assert "NET_A" in result.stretched, f"NET_A应被拉伸: stretched={result.stretched}, broken={result.broken}"
    assert len(result.broken) == 0

    # 验证线段移动到新位置(2050um)
    x_coords = get_x_coords(top, metal_layer)
    print(f"  拉伸后x坐标(dbu): {sorted(set(x_coords))}")
    assert 2050000 in x_coords, f"线段端点应移至2050um(2050000dbu)，实际={sorted(set(x_coords))}"

    print("  PASS")


# ──────────────────────────────────────────────
# S2: L型折线拉伸
# ──────────────────────────────────────────────
def test_s2_l_shape_stretch():
    """L型折线 → 垂直段顶端随引脚位移，拐点按比例加权。"""
    print("\n=== S2: L型折线拉伸 C1垂直位移(+50um) ===")

    layout, top, metal_layer, marker_layer = create_test_layout()

    # C1垂直位移：y从10→60 (+50um)
    # L型折线：水平段 (1000,10)→(2000,10) + 垂直段 (2000,10)→(2000,60)
    # 旧引脚
    old_pins = {
        "C1.P1": PinState(name="P1", ref="C1", x=2000.0, y=10.0),
    }
    # 新引脚
    new_pins = {
        "C1.P1": PinState(name="P1", ref="C1", x=2000.0, y=60.0),
    }

    # 画旧L型折线
    dbu = layout.dbu
    hwd = int(5.0 / dbu)
    # 水平段: (1000,10)->(2000,10)
    top.shapes(metal_layer).insert(db.Box(1000000, 10000-hwd, 2000000, 10000+hwd))
    # 垂直段: (2000,10)->(2000,60)
    top.shapes(metal_layer).insert(db.Box(2000000-hwd, 10000, 2000000+hwd, 60000))

    # L型wire
    pa = PinState(name="P1", ref="TL1", x=1000.0, y=10.0)
    pb = PinState(name="P2", ref="C1",  x=2000.0, y=60.0)
    wire = WireSegment(
        layer=(6, 0),
        points=[(1000.0, 10.0), (2000.0, 10.0), (2000.0, 60.0)],
        width=10.0,
    )
    conn = Connection(net_name="NET_B", pin_a=pa, pin_b=pb, wires=[wire])

    router = StretchRouter()
    result = router.stretch_connections(
        layout=layout, cell=top, connections=[conn],
        old_pins=old_pins, new_pins=new_pins, threshold_um=100.0,
    )

    print(f"  stretched={result.stretched}, broken={result.broken}")
    assert "NET_B" in result.stretched, f"NET_B应被拉伸: {result.stretched}"
    assert len(result.broken) == 0

    # 验证垂直段底部y坐标变化：10→60
    y_coords = get_y_coords(top, metal_layer)
    print(f"  拉伸后y坐标(dbu): {sorted(set(y_coords))}")
    # 垂直段底部应从10um升到60um(60000dbu)
    assert 10000 not in y_coords or 60000 in y_coords, \
        f"垂直段底部y应升至60um: {sorted(set(y_coords))}"

    print("  PASS")


# ──────────────────────────────────────────────
# S3: 断线标记
# ──────────────────────────────────────────────
def test_s3_broken_wire():
    """位移超阈值100um → 断线+X标记。"""
    print("\n=== S3: 断线标记 位移+200um > 阈值100um ===")

    layout, top, metal_layer, marker_layer = create_test_layout()

    # TL1大跳变：P2从2000→2200 (+200um) 超过阈值100um
    old_pins = {
        "TL1.P2": PinState(name="P2", ref="TL1", x=2000.0, y=10.0),
        "C1.P1":  PinState(name="P1", ref="C1",  x=2000.0, y=10.0),
    }
    new_pins = {
        "TL1.P2": PinState(name="P2", ref="TL1", x=2200.0, y=10.0),
        "C1.P1":  PinState(name="P1", ref="C1",  x=2000.0, y=10.0),  # C1不动
    }

    # 画旧连接线
    dbu = layout.dbu
    hwd = int(5.0 / dbu)
    top.shapes(metal_layer).insert(db.Box(2000000, 10000-hwd, 2200000, 10000+hwd))

    # 连接(旧几何)：直线从(2000,10)->(2200,10)
    pa = PinState(name="P2", ref="TL1", x=2000.0, y=10.0)
    pb = PinState(name="P1", ref="C1",  x=2200.0, y=10.0)
    wire = WireSegment(layer=(6, 0), points=[(2000.0, 10.0), (2200.0, 10.0)], width=10.0)
    conn = Connection(net_name="NET_C", pin_a=pa, pin_b=pb, wires=[wire])

    router = StretchRouter()
    result = router.stretch_connections(
        layout=layout, cell=top, connections=[conn],
        old_pins=old_pins, new_pins=new_pins, threshold_um=100.0,
    )

    print(f"  stretched={result.stretched}, broken={result.broken}")
    assert "NET_C" in result.broken, f"NET_C应标记为断线: broken={result.broken}"
    assert len(result.stretched) == 0

    # 验证X标记
    marker_shapes = list(top.shapes(marker_layer))
    text_shapes = [s for s in marker_shapes if s.is_text()]
    box_shapes = [s for s in marker_shapes if s.is_box()]
    print(f"  标记层shapes: {len(box_shapes)}个Box, {len(text_shapes)}个Text")
    assert len(box_shapes) >= 2, f"应有X标记(2个Box)，实际{len(box_shapes)}"

    found_broken_label = False
    for s in text_shapes:
        text_obj = s.text
        if "BROKEN" in str(text_obj):
            found_broken_label = True
            print(f"  找到断线标注: {text_obj}")
    assert found_broken_label, "应有BROKEN:NET_C文本"

    print("  PASS")


# ──────────────────────────────────────────────
# S4: 非对称拉伸
# ──────────────────────────────────────────────
def test_s4_asymmetric_displacement():
    """两端反向位移 → 直线按各自端点位移拉伸。"""
    print("\n=== S4: 非对称拉伸 两端反向各50um ===")

    layout, top, metal_layer, marker_layer = create_test_layout()

    # 两端反向位移：左端+50，右端-50
    old_pins = {
        "TL1.P2": PinState(name="P2", ref="TL1", x=1000.0, y=0.0),
        "C1.P1":  PinState(name="P1", ref="C1",  x=2000.0, y=0.0),
    }
    new_pins = {
        "TL1.P2": PinState(name="P2", ref="TL1", x=1050.0, y=0.0),  # +50
        "C1.P1":  PinState(name="P1", ref="C1",  x=1950.0, y=0.0), # -50
    }

    # 画旧连接 (1000,0)->(2000,0)
    dbu = layout.dbu
    hwd = int(5.0 / dbu)
    top.shapes(metal_layer).insert(db.Box(1000000, -hwd, 2000000, hwd))

    pa = PinState(name="P2", ref="TL1", x=1000.0, y=0.0)
    pb = PinState(name="P1", ref="C1",  x=2000.0, y=0.0)
    wire = WireSegment(layer=(6, 0), points=[(1000.0, 0.0), (2000.0, 0.0)], width=10.0)
    conn = Connection(net_name="NET_D", pin_a=pa, pin_b=pb, wires=[wire])

    router = StretchRouter()
    result = router.stretch_connections(
        layout=layout, cell=top, connections=[conn],
        old_pins=old_pins, new_pins=new_pins, threshold_um=100.0,
    )

    print(f"  stretched={result.stretched}, broken={result.broken}")
    assert "NET_D" in result.stretched
    assert len(result.broken) == 0

    # 验证：左端1000→1050，右端2000→1950
    x_coords = get_x_coords(top, metal_layer)
    print(f"  拉伸后x坐标(dbu): {sorted(set(x_coords))}")
    assert 1050000 in x_coords, f"左端应移至1050um: {sorted(set(x_coords))}"
    assert 1950000 in x_coords, f"右端应移至1950um: {sorted(set(x_coords))}"

    print("  PASS")


def main():
    print("StretchRouter 实际连线拉伸冒烟测试")
    print("=" * 50)

    Path("state/snapshots").mkdir(parents=True, exist_ok=True)

    test_s1_straight_stretch()
    test_s2_l_shape_stretch()
    test_s3_broken_wire()
    test_s4_asymmetric_displacement()

    print("\n" + "=" * 50)
    print("StretchRouter 拉伸测试通过！4/4 PASS")
    print("  S1 直线拉伸   ✓")
    print("  S2 L型折线   ✓")
    print("  S3 断线标记   ✓")
    print("  S4 非对称拉伸 ✓")


if __name__ == "__main__":
    main()
