"""传输线PCell全链路冒烟测试。

验证：PCell注册 → 几何生成(0°/90°) → 引脚位置(含旋转) →
      阻抗映射 → 参数校验 → 全链路更新 → 引脚位移差
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# 添加路径
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))
pcell_dir = Path(__file__).parent
sys.path.insert(0, str(pcell_dir))

import klayout.db as db
from parser.target_params import TargetParam
from mapper.engine import MappingEngine
from executor.klayout_executor import KLayoutExecutor
from pcells.base import PinPosition
from pcells.registry import get_pcell, list_pcells


def test_registry():
    """测试PCell注册表含传输线。"""
    print("\n=== 测试1: PCell注册表 ===")
    pcells = list_pcells()
    print(f"  已注册PCell: {list(pcells.keys())}")
    assert "TL_MICROSTRIP" in pcells, "TL_MICROSTRIP未注册"
    print("  PASS")


def test_generate_0deg():
    """测试0°方向几何生成（水平）。"""
    print("\n=== 测试2: 0°几何生成 ===")
    pcell = get_pcell("TL_MICROSTRIP")
    layout = db.Layout()
    layout.dbu = 0.001
    cell = layout.create_cell("TL_0deg")

    params = {"width": 20, "length": 1000, "angle": 0.0}
    pcell.generate(cell, params)

    metal_layer = layout.layer(6, 0)
    shapes = list(cell.each_shape(metal_layer))
    print(f"  Metal层形状数: {len(shapes)}")
    assert len(shapes) >= 1, "Metal层无形状"

    # 检查bbox（0°: 水平长条），用metal层bbox避免引脚标记干扰
    bbox = cell.bbox_per_layer(metal_layer)
    print(f"  metal bbox: ({bbox.left}, {bbox.bottom}) → ({bbox.right}, {bbox.top}) dbu")
    # 宽度=20um → 20000dbu, 长度=1000um → 1000000dbu
    assert abs(bbox.right - bbox.left - 1000000) < 100, "0°长度不正确"
    assert abs(bbox.top - bbox.bottom - 20000) < 100, "0°宽度不正确"
    print("  PASS")


def test_generate_90deg():
    """测试90°方向几何生成（垂直）。"""
    print("\n=== 测试3: 90°几何生成 ===")
    pcell = get_pcell("TL_MICROSTRIP")
    layout = db.Layout()
    layout.dbu = 0.001
    cell = layout.create_cell("TL_90deg")

    params = {"width": 20, "length": 1000, "angle": 90.0}
    pcell.generate(cell, params)

    metal_layer = layout.layer(6, 0)
    shapes = list(cell.each_shape(metal_layer))
    print(f"  Metal层形状数: {len(shapes)}")
    assert len(shapes) >= 1, "Metal层无形状"

    # 检查bbox（90°: 垂直长条），用metal层bbox
    bbox = cell.bbox_per_layer(metal_layer)
    print(f"  metal bbox: ({bbox.left}, {bbox.bottom}) → ({bbox.right}, {bbox.top}) dbu")
    # 旋转90°后：长度方向变为y轴
    assert abs(bbox.top - bbox.bottom - 1000000) < 100, "90°长度(y方向)不正确"
    assert abs(bbox.right - bbox.left - 20000) < 100, "90°宽度(x方向)不正确"
    print("  PASS")


def test_pin_positions_0deg():
    """测试0°引脚位置。"""
    print("\n=== 测试4: 0°引脚位置 ===")
    pcell = get_pcell("TL_MICROSTRIP")
    params = {"width": 20, "length": 1000, "angle": 0.0}
    pins = pcell.get_pin_positions(params)

    print(f"  P1: ({pins['P1'].x:.1f}, {pins['P1'].y:.1f})")
    print(f"  P2: ({pins['P2'].x:.1f}, {pins['P2'].y:.1f})")

    # 0°: P1@(0,0), P2@(1000,0)
    assert abs(pins["P1"].x - 0.0) < 0.01, "P1.x应为0"
    assert abs(pins["P1"].y - 0.0) < 0.01, "P1.y应为0"
    assert abs(pins["P2"].x - 1000.0) < 0.01, "P2.x应为1000"
    assert abs(pins["P2"].y - 0.0) < 0.01, "P2.y应为0"
    print("  PASS")


def test_pin_positions_90deg():
    """测试90°引脚位置。"""
    print("\n=== 测试5: 90°引脚位置 ===")
    pcell = get_pcell("TL_MICROSTRIP")
    params = {"width": 20, "length": 1000, "angle": 90.0}
    pins = pcell.get_pin_positions(params)

    print(f"  P1: ({pins['P1'].x:.1f}, {pins['P1'].y:.1f})")
    print(f"  P2: ({pins['P2'].x:.1f}, {pins['P2'].y:.1f})")

    # 90°: P1@(0,0), P2@(0,1000)
    assert abs(pins["P1"].x - 0.0) < 0.01, "P1.x应为0"
    assert abs(pins["P1"].y - 0.0) < 0.01, "P1.y应为0"
    assert abs(pins["P2"].x - 0.0) < 0.01, "P2.x应为0"
    assert abs(pins["P2"].y - 1000.0) < 0.01, "P2.y应为1000"
    print("  PASS")


def test_impedance_mapping():
    """测试阻抗查表映射。"""
    print("\n=== 测试6: 阻抗映射 ===")
    mapper = MappingEngine("pcells/transmission_line/mapping.yaml")

    # 50Ω / 1000um
    target = TargetParam(reference="TL1", device_type="TL_MICROSTRIP",
                         params={"impedance_ohm": 50, "length_um": 1000})
    mg = mapper.map(target)
    print(f"  50Ω/1000um → width={mg.geometry_params.get('width')}um")
    assert mg.geometry_params.get("width") == 20, "50Ω应对应width=20um"

    # 72Ω / 2000um
    target2 = TargetParam(reference="TL2", device_type="TL_MICROSTRIP",
                          params={"impedance_ohm": 72, "length_um": 2000})
    mg2 = mapper.map(target2)
    print(f"  72Ω/2000um → width={mg2.geometry_params.get('width')}um")
    assert mg2.geometry_params.get("width") == 10, "72Ω应对应width=10um"

    print("  PASS")


def test_param_validation():
    """测试参数校验。"""
    print("\n=== 测试7: 参数校验 ===")
    pcell = get_pcell("TL_MICROSTRIP")

    # 合法
    valid, errors = pcell.validate_params({"width": 20, "length": 1000, "angle": 0})
    assert valid, f"合法参数校验失败: {errors}"
    print(f"  合法参数: PASS")

    # 非法width
    valid, errors = pcell.validate_params({"width": 1, "length": 1000, "angle": 0})
    assert not valid, "width=1应拦截"
    print(f"  width=1: 拦截正确 - {errors}")

    # 非法length
    valid, errors = pcell.validate_params({"width": 20, "length": 10, "angle": 0})
    assert not valid, "length=10应拦截"
    print(f"  length=10: 拦截正确 - {errors}")
    print("  PASS")


def test_full_pipeline():
    """测试全链路：映射 → PCell生成 → GDS更新。"""
    print("\n=== 测试8: 全链路更新 ===")

    mapper = MappingEngine("pcells/transmission_line/mapping.yaml")
    target = TargetParam(reference="TL1", device_type="TL_MICROSTRIP",
                         params={"impedance_ohm": 50, "length_um": 1000})
    mg = mapper.map(target)
    print(f"  映射: TL1 50Ω/1000um → {mg.geometry_params}")

    # 创建初始GDS（500um长）
    pcell = get_pcell("TL_MICROSTRIP")
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TOP")
    tl_cell = layout.create_cell("TL1_TL_MICROSTRIP")
    pcell.generate(tl_cell, {"width": 20, "length": 500, "angle": 0})
    top.insert(db.CellInstArray(tl_cell.cell_index(), db.Trans(db.Point(0, 0))))
    layout.write("state/snapshots/tl_initial.gds")

    # 执行更新：500um → 1000um（映射结果中length不一定有，因为mapping只给width）
    # 补全参数
    full_params = dict(mg.geometry_params)
    full_params.setdefault("length", 1000)
    full_params.setdefault("angle", 0.0)
    mg.geometry_params = full_params

    executor = KLayoutExecutor()
    result = executor.execute(
        gds_path="state/snapshots/tl_initial.gds",
        mapped_geometries=[mg],
        output_path="state/snapshots/tl_updated.gds",
    )

    print(f"  更新结果: success={result.success}")
    print(f"  更新器件: {result.updated_cells}")
    assert result.success, f"全链路更新失败: {result.errors}"
    assert Path("state/snapshots/tl_updated.gds").exists(), "输出GDS不存在"
    print("  PASS")


def test_pin_displacement():
    """测试引脚位移差：StretchRouter的直接输入。"""
    print("\n=== 测试9: 引脚位移差 ===")
    pcell = get_pcell("TL_MICROSTRIP")

    # 0°: length 500 → 1000
    old_pins = pcell.get_pin_positions({"width": 20, "length": 500, "angle": 0.0})
    new_pins = pcell.get_pin_positions({"width": 20, "length": 1000, "angle": 0.0})
    delta_p2 = (new_pins["P2"].x - old_pins["P2"].x,
                new_pins["P2"].y - old_pins["P2"].y)
    print(f"  0° ΔP2 = ({delta_p2[0]:.0f}, {delta_p2[1]:.0f}) um")
    assert abs(delta_p2[0] - 500.0) < 0.01, "0° ΔP2.x应为500"
    assert abs(delta_p2[1] - 0.0) < 0.01, "0° ΔP2.y应为0"

    # 90°: length 500 → 1000
    old_pins_90 = pcell.get_pin_positions({"width": 20, "length": 500, "angle": 90.0})
    new_pins_90 = pcell.get_pin_positions({"width": 20, "length": 1000, "angle": 90.0})
    delta_p2_90 = (new_pins_90["P2"].x - old_pins_90["P2"].x,
                   new_pins_90["P2"].y - old_pins_90["P2"].y)
    print(f"  90° ΔP2 = ({delta_p2_90[0]:.0f}, {delta_p2_90[1]:.0f}) um")
    assert abs(delta_p2_90[0] - 0.0) < 0.01, "90° ΔP2.x应为0"
    assert abs(delta_p2_90[1] - 500.0) < 0.01, "90° ΔP2.y应为500"

    print("  PASS")


def test_bounding_box():
    """测试包围盒计算。"""
    print("\n=== 测试10: 包围盒 ===")
    pcell = get_pcell("TL_MICROSTRIP")

    # 0°
    bb = pcell.get_bounding_box({"width": 20, "length": 1000, "angle": 0.0})
    print(f"  0° bbox: ({bb[0]:.0f},{bb[1]:.0f}) → ({bb[2]:.0f},{bb[3]:.0f})")
    assert abs(bb[2] - bb[0] - 1000) < 0.1, "0° bbox宽度应为1000"
    assert abs(bb[3] - bb[1] - 20) < 0.1, "0° bbox高度应为20"

    # 90°
    bb90 = pcell.get_bounding_box({"width": 20, "length": 1000, "angle": 90.0})
    print(f"  90° bbox: ({bb90[0]:.0f},{bb90[1]:.0f}) → ({bb90[2]:.0f},{bb90[3]:.0f})")
    assert abs(bb90[3] - bb90[1] - 1000) < 0.1, "90° bbox高度应为1000"
    assert abs(bb90[2] - bb90[0] - 20) < 0.1, "90° bbox宽度应为20"

    print("  PASS")


def main():
    print("传输线PCell 全链路冒烟测试")
    print("=" * 40)

    Path("state/snapshots").mkdir(parents=True, exist_ok=True)

    test_registry()
    test_generate_0deg()
    test_generate_90deg()
    test_pin_positions_0deg()
    test_pin_positions_90deg()
    test_impedance_mapping()
    test_param_validation()
    test_full_pipeline()
    test_pin_displacement()
    test_bounding_box()

    print("\n" + "=" * 40)
    print("传输线全链路测试通过！10/10 PASS")
    print("  registry ✓  generate(0°/90°) ✓  pins(0°/90°) ✓")
    print("  mapping ✓  validation ✓  full_pipeline ✓")
    print("  pin_displacement ✓  bounding_box ✓")


if __name__ == "__main__":
    main()
