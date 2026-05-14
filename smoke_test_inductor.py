"""螺旋电感PCell全链路冒烟测试。

验证：注册→几何生成(2圈/3圈/3.5圈)→引脚位置→映射→参数校验→
      DRC联动→全链路更新
"""

from __future__ import annotations

import sys
from pathlib import Path

src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))
pcell_dir = Path(__file__).parent
sys.path.insert(0, str(pcell_dir))

import klayout.db as db
from parser.target_params import TargetParam
from mapper.engine import MappingEngine
from executor.klayout_executor import KLayoutExecutor
from validator.drc_runner import KLayoutDRCRunner
from validator.ref_mapper import ViolationRefMapper
from pcells.base import PinPosition
from pcells.registry import get_pcell, list_pcells


def test_registry():
    print("\n=== 测试1: PCell注册表 ===")
    pcells = list_pcells()
    print(f"  已注册: {list(pcells.keys())}")
    assert "IND_SPIRAL" in pcells
    print("  PASS")


def test_generate_2turns():
    print("\n=== 测试2: 2.0圈几何生成 ===")
    pcell = get_pcell("IND_SPIRAL")
    layout = db.Layout()
    layout.dbu = 0.001
    cell = layout.create_cell("IND_2T")

    params = {"inner_radius": 30, "turns": 2.0, "width": 10, "spacing": 8, "angle": 0.0}
    pcell.generate(cell, params)

    # 验证各层形状
    top_layer = layout.layer(7, 0)
    under_layer = layout.layer(6, 0)
    via_layer = layout.layer(11, 0)

    top_count = len(list(cell.each_shape(top_layer)))
    under_count = len(list(cell.each_shape(under_layer)))
    via_count = len(list(cell.each_shape(via_layer)))

    print(f"  顶层走线段数: {top_count}")
    print(f"  Underpass段数: {under_count}")
    print(f"  通孔数: {via_count}")

    # 2圈: 4段/圈 × 2圈 = 8段顶层走线 + 1段Underpass + 2个通孔
    assert top_count == 8, f"2圈应有8段顶层走线，实际{top_count}"
    assert under_count == 1, f"应有1段Underpass，实际{under_count}"
    assert via_count == 2, f"应有2个通孔，实际{via_count}"

    # 验证外圈尺寸
    bbox = cell.bbox_per_layer(top_layer)
    dbu = layout.dbu
    w_um = (bbox.right - bbox.left) * dbu
    h_um = (bbox.top - bbox.bottom) * dbu
    print(f"  外圈bbox: {w_um:.0f}x{h_um:.0f} um")
    # ir=30, turns=2, w=10, s=8: outer_half = 30 + 1*18 + 10 = 58
    assert abs(w_um - 116) < 5, f"外圈宽度应约116um，实际{w_um}"

    layout.write("state/snapshots/inductor_2turns.gds")
    print("  PASS")


def test_generate_3turns():
    print("\n=== 测试3: 3.0圈几何生成 ===")
    pcell = get_pcell("IND_SPIRAL")
    layout = db.Layout()
    layout.dbu = 0.001
    cell = layout.create_cell("IND_3T")

    params = {"inner_radius": 50, "turns": 3.0, "width": 10, "spacing": 8, "angle": 0.0}
    pcell.generate(cell, params)

    top_layer = layout.layer(7, 0)
    top_count = len(list(cell.each_shape(top_layer)))
    print(f"  顶层走线段数: {top_count}")
    assert top_count == 12, f"3圈应有12段顶层走线，实际{top_count}"

    bbox = cell.bbox_per_layer(top_layer)
    dbu = layout.dbu
    w_um = (bbox.right - bbox.left) * dbu
    print(f"  外圈宽度: {w_um:.0f} um")
    # ir=50, turns=3, w=10, s=8: outer_half = 50 + 2*18 + 10 = 96
    assert abs(w_um - 192) < 5, f"外圈宽度应约192um，实际{w_um}"
    print("  PASS")


def test_generate_half_turn():
    print("\n=== 测试4: 3.5圈几何生成(半圈) ===")
    pcell = get_pcell("IND_SPIRAL")
    layout = db.Layout()
    layout.dbu = 0.001
    cell = layout.create_cell("IND_35T")

    params = {"inner_radius": 50, "turns": 3.5, "width": 10, "spacing": 8, "angle": 0.0}
    pcell.generate(cell, params)

    top_layer = layout.layer(7, 0)
    top_count = len(list(cell.each_shape(top_layer)))
    print(f"  顶层走线段数: {top_count}")
    # 3完整圈=12段 + 1段半圈顶边 = 13段
    assert top_count == 13, f"3.5圈应有13段顶层走线，实际{top_count}"
    print("  PASS")


def test_pin_positions():
    print("\n=== 测试5: 引脚位置 ===")
    pcell = get_pcell("IND_SPIRAL")

    # 2.0圈
    params = {"inner_radius": 30, "turns": 2.0, "width": 10, "spacing": 8, "angle": 0.0}
    pins = pcell.get_pin_positions(params)
    print(f"  2.0圈: PI=({pins['PI'].x:.1f},{pins['PI'].y:.1f}), "
          f"NIN=({pins['NIN'].x:.1f},{pins['NIN'].y:.1f})")
    # outer_half=58, PI=(0,58), NIN=(-30,-58)
    assert abs(pins["PI"].y - 58) < 0.1, f"PI.y应为58，实际{pins['PI'].y}"
    assert abs(pins["NIN"].y - (-58)) < 0.1, f"NIN.y应为-58，实际{pins['NIN'].y}"

    # 3.5圈
    params35 = {"inner_radius": 50, "turns": 3.5, "width": 10, "spacing": 8, "angle": 0.0}
    pins35 = pcell.get_pin_positions(params35)
    print(f"  3.5圈: PI=({pins35['PI'].x:.1f},{pins35['PI'].y:.1f}), "
          f"NIN=({pins35['NIN'].x:.1f},{pins35['NIN'].y:.1f})")
    # outer_half = 50 + 3*18 + 10 = 114
    assert abs(pins35["PI"].y - 114) < 0.1, f"PI.y应为114，实际{pins35['PI'].y}"
    print("  PASS")


def test_mapping():
    print("\n=== 测试6: 电感值映射 ===")
    mapper = MappingEngine("config/mapping_rules.yaml")

    target = TargetParam(reference="L1", device_type="inductor_spiral",
                         params={"inductance_nH": 2.0})
    mg = mapper.map(target)
    print(f"  2.0nH → {mg.geometry_params}")
    assert mg.target_pcell == "IND_SPIRAL"
    assert mg.geometry_params["turns"] == 3.0, "2nH应对应turns=3.0"
    assert mg.geometry_params["inner_radius"] == 50, "2nH应对应ir=50"
    assert mg.geometry_params.get("spacing") == 8.0, "默认spacing=8"
    print("  PASS")


def test_param_validation():
    print("\n=== 测试7: 参数校验 ===")
    pcell = get_pcell("IND_SPIRAL")

    # 合法
    valid, errors = pcell.validate_params(
        {"inner_radius": 50, "turns": 3.0, "width": 10, "spacing": 8}
    )
    assert valid, f"合法参数校验失败: {errors}"
    print("  合法参数: PASS")

    # 非法turns
    valid, errors = pcell.validate_params(
        {"inner_radius": 50, "turns": 0.5, "width": 10, "spacing": 8}
    )
    assert not valid, "turns=0.5应拦截"
    print(f"  turns=0.5: 拦截正确 - {errors}")
    print("  PASS")


def test_drc_with_inductor():
    print("\n=== 测试8: DRC联动(电感) ===")
    # 创建一个3圈电感的GDS
    pcell = get_pcell("IND_SPIRAL")
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TOP")
    ind_cell = layout.create_cell("L1_IND_SPIRAL")
    pcell.generate(ind_cell, {"inner_radius": 50, "turns": 3.0, "width": 10, "spacing": 8, "angle": 0.0})
    top.insert(db.CellInstArray(ind_cell.cell_index(), db.Trans(db.Point(0, 0))))

    gds_path = "state/snapshots/inductor_drc.gds"
    layout.write(gds_path)

    # 运行DRC
    drc_runner = KLayoutDRCRunner()
    result = drc_runner.run(gds_path, "config/drc_rules/simple_rf.yaml")

    print(f"  DRC passed={result.passed}, violations={result.violation_count}")
    if result.violations:
        for v in result.violations[:5]:
            print(f"    {v.rule_name}: {v.description} @ ({v.x:.1f},{v.y:.1f})")

    # 电感的spacing=8um，远大于DRC最小间距1.0um，应该通过
    # 但metal2.min_width=3.0um，线宽10um也合规
    assert result.passed, f"合规电感DRC应通过: {result.violation_count}违例"
    print("  PASS")


def test_full_pipeline():
    print("\n=== 测试9: 全链路更新(1nH→3nH) ===")
    mapper = MappingEngine("config/mapping_rules.yaml")

    # 创建初始GDS: 1nH电感
    pcell = get_pcell("IND_SPIRAL")
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TOP")
    ind_cell = layout.create_cell("L1_IND_SPIRAL")
    # 1nH: ir=35, turns=2.0, w=10, s=8
    pcell.generate(ind_cell, {"inner_radius": 35, "turns": 2.0, "width": 10, "spacing": 8, "angle": 0.0})
    top.insert(db.CellInstArray(ind_cell.cell_index(), db.Trans(db.Point(0, 0))))
    layout.write("state/snapshots/ind_initial.gds")

    # 映射3nH
    target = TargetParam(reference="L1", device_type="inductor_spiral",
                         params={"inductance_nH": 3.0})
    mg = mapper.map(target)
    print(f"  3nH映射: {mg.geometry_params}")

    # 执行更新
    executor = KLayoutExecutor()
    result = executor.execute(
        gds_path="state/snapshots/ind_initial.gds",
        mapped_geometries=[mg],
        output_path="state/snapshots/ind_updated.gds",
    )

    assert result.success, f"全链路更新失败: {result.errors}"
    assert "L1" in result.updated_cells

    # DRC验证更新后GDS
    drc_result = KLayoutDRCRunner().run(
        "state/snapshots/ind_updated.gds", "config/drc_rules/simple_rf.yaml"
    )
    print(f"  DRC: passed={drc_result.passed}, violations={drc_result.violation_count}")
    assert drc_result.passed, f"更新后DRC应通过: {drc_result.violation_count}违例"
    print("  PASS")


def test_bounding_box():
    print("\n=== 测试10: 包围盒 ===")
    pcell = get_pcell("IND_SPIRAL")
    params = {"inner_radius": 30, "turns": 2.0, "width": 10, "spacing": 8, "angle": 0.0}
    bb = pcell.get_bounding_box(params)
    print(f"  bbox: ({bb[0]:.0f},{bb[1]:.0f}) → ({bb[2]:.0f},{bb[3]:.0f})")
    assert abs(bb[2] - bb[0] - 116) < 1, f"bbox宽度应约116um"
    assert abs(bb[3] - bb[1] - 116) < 1, f"bbox高度应约116um"
    print("  PASS")


def main():
    print("螺旋电感PCell 全链路冒烟测试")
    print("=" * 40)

    Path("state/snapshots").mkdir(parents=True, exist_ok=True)

    test_registry()
    test_generate_2turns()
    test_generate_3turns()
    test_generate_half_turn()
    test_pin_positions()
    test_mapping()
    test_param_validation()
    test_drc_with_inductor()
    test_full_pipeline()
    test_bounding_box()

    print("\n" + "=" * 40)
    print("螺旋电感全链路测试通过！10/10 PASS")
    print("  registry ✓  2圈 ✓  3圈 ✓  3.5圈 ✓")
    print("  引脚位置 ✓  映射 ✓  校验 ✓")
    print("  DRC联动 ✓  全链路 ✓  包围盒 ✓")


if __name__ == "__main__":
    main()
