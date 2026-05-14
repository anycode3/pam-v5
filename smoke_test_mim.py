"""MIM电容PCell全链路冒烟测试。

验证：目标参数 → 映射 → PCell生成 → GDS更新 → 引脚位置正确
"""

from __future__ import annotations

import sys
from pathlib import Path

# 添加路径
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))
pcell_dir = Path(__file__).parent
sys.path.insert(0, str(pcell_dir))

import klayout.db as db
from parser.target_params import TargetParamsParser, TargetParam
from mapper.engine import MappingEngine
from executor.klayout_executor import KLayoutExecutor
from pcells.base import PinPosition
from pcells.registry import get_pcell, list_pcells


def test_pcell_registry():
    """测试PCell注册表。"""
    print("\n=== 测试1: PCell注册表 ===")
    pcells = list_pcells()
    print(f"  已注册PCell: {list(pcells.keys())}")
    assert "CAP_MIM" in pcells, "CAP_MIM未注册"
    print("  PASS")


def test_mim_pcell_generate():
    """测试MIM电容PCell几何生成。"""
    print("\n=== 测试2: MIM电容PCell生成 ===")
    pcell = get_pcell("CAP_MIM")
    print(f"  参数定义: {pcell.get_parameters()}")
    print(f"  引脚: {pcell.get_pins()}")

    # 创建layout和cell
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TOP")
    cap_cell = layout.create_cell("C1_CAP_MIM")

    # 生成2pF电容
    params = {"length": 57, "width": 57}
    pcell.generate(cap_cell, params)

    # 验证几何
    mt_layer = layout.layer(10, 0)
    mb_layer = layout.layer(8, 0)
    mim_layer = layout.layer(9, 0)

    mt_shapes = list(cap_cell.each_shape(mt_layer))
    mb_shapes = list(cap_cell.each_shape(mb_layer))
    mim_shapes = list(cap_cell.each_shape(mim_layer))

    print(f"  MT层形状数: {len(mt_shapes)}")
    print(f"  MB层形状数: {len(mb_shapes)}")
    print(f"  MIM层形状数: {len(mim_shapes)}")

    assert len(mt_shapes) >= 1, "MT层无形状"
    assert len(mb_shapes) >= 1, "MB层无形状"
    assert len(mim_shapes) >= 1, "MIM层无形状"

    top.insert(db.CellInstArray(cap_cell.cell_index(), db.Trans(db.Point(0, 0))))
    layout.write("state/snapshots/mim_cap_test.gds")
    print(f"  GDS已保存: state/snapshots/mim_cap_test.gds")
    print("  PASS")


def test_mim_pin_positions():
    """测试MIM电容引脚位置。"""
    print("\n=== 测试3: MIM电容引脚位置 ===")
    pcell = get_pcell("CAP_MIM")

    # 2pF: 57x57um
    params = {"length": 57, "width": 57}
    pins = pcell.get_pin_positions(params)
    for name, pos in pins.items():
        print(f"  {name}: ({pos.x:.1f}, {pos.y:.1f}) um, layer={pos.layer}")

    assert "PI" in pins, "缺少PI引脚"
    assert "NIN" in pins, "缺少NIN引脚"
    assert pins["PI"].x == 57 + 10, "PI引脚x坐标不正确"  # length + pin_length
    assert pins["PI"].y == 57 / 2, "PI引脚y坐标不正确"   # width / 2
    print("  PASS")


def test_mim_param_validation():
    """测试MIM电容参数校验。"""
    print("\n=== 测试4: MIM电容参数校验 ===")
    pcell = get_pcell("CAP_MIM")

    # 合法参数
    valid, errors = pcell.validate_params({"length": 57, "width": 57})
    assert valid, f"合法参数校验失败: {errors}"
    print(f"  合法参数 (57x57): PASS")

    # 非法参数
    valid, errors = pcell.validate_params({"length": 5, "width": 300})
    assert not valid, "非法参数应校验失败"
    print(f"  非法参数 (5x300): 拦截正确 - {errors}")
    print("  PASS")


def test_full_pipeline():
    """测试完整链路：目标参数 → 映射 → PCell → GDS。"""
    print("\n=== 测试5: 全链路（仅MIM电容）===")

    # 1. 解析目标参数（手动构造，只测MIM电容）
    targets = [
        TargetParam(reference="C1", device_type="capacitor_mim", params={"capacitance_pf": 2.0}),
    ]

    # 2. 映射（使用MIM专用mapping.yaml）
    mapper = MappingEngine("pcells/mim_capacitor/mapping.yaml")
    mapped = mapper.map_all(targets)
    print(f"  映射: C1 2pF → {mapped[0].geometry_params}")

    # 3. 创建初始GDS（用PCell生成）
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TOP")
    cap_cell = layout.create_cell("C1_CAP_MIM")

    # 先用1pF参数生成初始版图
    pcell = get_pcell("CAP_MIM")
    initial_params = {"length": 40, "width": 40}
    pcell.generate(cap_cell, initial_params)
    top.insert(db.CellInstArray(cap_cell.cell_index(), db.Trans(db.Point(0, 0))))
    layout.write("state/snapshots/mim_initial.gds")
    print(f"  初始GDS: 1pF (40x40um)")

    # 4. 执行更新：1pF → 2pF
    executor = KLayoutExecutor()
    result = executor.execute(
        gds_path="state/snapshots/mim_initial.gds",
        mapped_geometries=mapped,
        output_path="state/snapshots/mim_updated.gds",
    )

    print(f"  更新结果: success={result.success}")
    print(f"  更新器件: {result.updated_cells}")
    print(f"  错误: {result.errors}")

    assert result.success, f"全链路更新失败: {result.errors}"
    assert "C1" in result.updated_cells, "C1未被更新"
    assert Path("state/snapshots/mim_updated.gds").exists(), "输出GDS不存在"
    print("  PASS")


def test_different_capacitance_values():
    """测试不同电容值的PCell生成。"""
    print("\n=== 测试6: 多电容值PCell生成 ===")
    pcell = get_pcell("CAP_MIM")

    for cap_pf in [0.5, 1.0, 2.0, 5.0, 10.0]:
        mapper = MappingEngine("pcells/mim_capacitor/mapping.yaml")
        target = TargetParam(reference=f"C_{cap_pf}", device_type="capacitor_mim", params={"capacitance_pf": cap_pf})
        mg = mapper.map(target)

        layout = db.Layout()
        layout.dbu = 0.001
        cap_cell = layout.create_cell(f"C_{cap_pf}pF")
        pcell.generate(cap_cell, mg.geometry_params)

        pins = pcell.get_pin_positions(mg.geometry_params)
        print(f"  {cap_pf}pF → {mg.geometry_params} → PI@({pins['PI'].x:.0f},{pins['PI'].y:.0f})")

    print("  PASS")


def main():
    print("MIM电容PCell 全链路冒烟测试")
    print("=" * 40)

    Path("state/snapshots").mkdir(parents=True, exist_ok=True)

    test_pcell_registry()
    test_mim_pcell_generate()
    test_mim_pin_positions()
    test_mim_param_validation()
    test_full_pipeline()
    test_different_capacitance_values()

    print("\n" + "=" * 40)
    print("MIM电容全链路测试通过！6/6 PASS")
    print("  registry ✓  generate ✓  pin_positions ✓")
    print("  validation ✓  full_pipeline ✓  multi_values ✓")


if __name__ == "__main__":
    main()
