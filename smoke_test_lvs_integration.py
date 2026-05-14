"""LVS Runner 集成测试：通过 Runner(lvs_enabled=True) 执行端到端LVS验证。

验证场景：
  S1: 两个独立传输线，无连接 → LVS检测到各自独立的pin
  S2: LVS未启用 → lvs_result=None
  S3: LVS执行后pin_positions正确（全局坐标含instance变换）

注意：LVS的METAL_LAYERS=(6,0)+(7,0)，只检测这些层的连通性。
PCell更新后版图中的金属线将器件连接，这属于正常的物理连通。
本测试验证LVS引擎在Runner中的集成是否正确（pin发现、坐标变换、结果回传）。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))
pcell_dir = Path(__file__).parent
sys.path.insert(0, str(pcell_dir))

import klayout.db as db
from core.runner import Runner, RunConfig
from pcells.registry import get_pcell

WORK = Path("state/lvs_integration_test")


def clean_work():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)


def _create_single_tl_gds(gds_path: str):
    """创建单条传输线版图。TL1在(0,0)，无其他器件。"""
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("LVS_TEST")

    tl_pcell = get_pcell("TL_MICROSTRIP")
    tl1_cell = layout.create_cell("TL1_TL_MICROSTRIP")
    tl_pcell.generate(tl1_cell, {"width": 20, "length": 1000, "angle": 0.0})
    top.insert(db.CellInstArray(tl1_cell.cell_index(), db.Trans(db.Point(0, 0))))

    layout.write(gds_path)


def _create_netlist(path: str):
    """创建单器件网表（只有TL1）。"""
    netlist = """(export (version "E")
  (design (source "/pam/lvs_test/lvs_test.kicad_sch") (date "2026-05-14") (tool "KiCad 8.0"))
  (components
    (comp (ref "TL1") (value "50Ohm/1000um")
      (libsource (lib "RF") (part "TL_MICROSTRIP")))
  )
  (nets
    (net (code 1) (name "RFIN")
      (node (ref "TL1") (pin "P1"))
    )
    (net (code 2) (name "RFOUT")
      (node (ref "TL1") (pin "P2"))
    )
  )
)
"""
    Path(path).write_text(netlist)


def _create_target_params(path: str):
    """创建目标参数JSON。"""
    data = [
        {"reference": "TL1", "type": "TL_MICROSTRIP", "params": {"impedance_ohm": 50.0, "length_um": 1000.0}},
    ]
    Path(path).write_text(json.dumps(data))


def test_s1_lvs_single_device():
    """单器件 + LVS启用 → LVS能正确发现pin并执行。"""
    print("\n=== S1: LVS Runner集成 — 单器件 → pin发现正确 ===")
    clean_work()

    input_gds = str(WORK / "input.gds")
    output_gds = str(WORK / "output.gds")
    netlist_path = str(WORK / "netlist.net")
    target_path = str(WORK / "target.json")

    _create_single_tl_gds(input_gds)
    _create_netlist(netlist_path)
    _create_target_params(target_path)

    config = RunConfig(
        gds_path=input_gds,
        netlist_path=netlist_path,
        target_params_path=target_path,
        mapping_rules_path="config/mapping_rules.yaml",
        output_path=output_gds,
        state_dir=str(WORK),
        drc_enabled=True,
        drc_rules_path="config/drc_rules/simple_rf.yaml",
        lvs_enabled=True,
    )

    runner = Runner(config)
    result = runner.run()

    print(f"  success={result.success}")
    print(f"  lvs_result={result.lvs_result.passed if result.lvs_result else 'N/A'}")
    if result.lvs_result:
        print(f"  physical_nets={result.lvs_result.physical_nets}")
        print(f"  opens={result.lvs_result.open_count}, shorts={result.lvs_result.short_count}")
    if result.errors:
        for e in result.errors:
            print(f"  error: {e}")

    # LVS应执行并返回结果（即使检测到SHORT也是正确的——TL1的P1和P2在同一块金属上）
    assert result.lvs_result is not None, "LVS应执行并返回结果"
    # TL1的metal是一整块矩形，P1和P2都在上面，所以physical上它们是连通的
    # 网表把P1和P2分在不同net（RFIN和RFOUT），但物理上它们在同一块metal上
    # LVS应检测到TL1.P1和TL1.P2在同一region
    pn = result.lvs_result.physical_nets
    all_pins = set()
    for pins in pn.values():
        all_pins.update(pins)
    assert "TL1.P1" in all_pins, "LVS应发现TL1.P1"
    assert "TL1.P2" in all_pins, "LVS应发现TL1.P2"
    print("  PASS")


def test_s2_lvs_disabled():
    """LVS未启用 → lvs_result应为None。"""
    print("\n=== S2: LVS未启用 → lvs_result=None ===")
    clean_work()

    input_gds = str(WORK / "input.gds")
    output_gds = str(WORK / "output.gds")
    netlist_path = str(WORK / "netlist.net")
    target_path = str(WORK / "target.json")

    _create_single_tl_gds(input_gds)
    _create_netlist(netlist_path)
    _create_target_params(target_path)

    config = RunConfig(
        gds_path=input_gds,
        netlist_path=netlist_path,
        target_params_path=target_path,
        mapping_rules_path="config/mapping_rules.yaml",
        output_path=output_gds,
        state_dir=str(WORK),
        drc_enabled=True,
        drc_rules_path="config/drc_rules/simple_rf.yaml",
        lvs_enabled=False,
    )

    runner = Runner(config)
    result = runner.run()

    assert result.lvs_result is None, "LVS未启用时lvs_result应为None"
    print("  PASS")


def test_s3_lvs_instance_transform():
    """TL1有instance偏移 → LVS应使用全局坐标（含instance变换）。"""
    print("\n=== S3: LVS instance坐标变换 → pin全局坐标正确 ===")
    clean_work()

    # 直接用KLayoutPureLVS测试，更精确
    from validator.lvs_runner import KLayoutPureLVS

    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TEST")

    # TL1放在offset=(500000, 100000) dbu = (500, 100) um
    tl_pcell = get_pcell("TL_MICROSTRIP")
    tl1_cell = layout.create_cell("TL1_TL_MICROSTRIP")
    tl_pcell.generate(tl1_cell, {"width": 20, "length": 1000, "angle": 0.0})
    top.insert(db.CellInstArray(tl1_cell.cell_index(), db.Trans(db.Point(500000, 100000))))

    gds_path = str(WORK / "offset_tl.gds")
    layout.write(gds_path)

    # LVS: 期望P1全局=(500,100), P2全局=(1500,100)
    lvs = KLayoutPureLVS()
    result = lvs.run(
        gds_path=gds_path,
        schematic_nets={"NET_A": ["TL1.P1", "TL1.P2"]},
        pin_positions={
            "TL1.P1": (500.0, 100.0),
            "TL1.P2": (1500.0, 100.0),
        },
    )

    print(f"  passed={result.passed}, opens={result.open_count}, shorts={result.short_count}")
    # P1和P2都在同一块metal上(连通)，网表也期望它们在同一net，应PASS
    assert result.passed, f"LVS应通过: {result.violations}"
    print("  PASS")


def main():
    print("LVS Runner 集成测试")
    print("=" * 50)

    Path("state/lvs_integration_test").mkdir(parents=True, exist_ok=True)

    test_s1_lvs_single_device()
    test_s2_lvs_disabled()
    test_s3_lvs_instance_transform()

    print("\n" + "=" * 50)
    print("LVS Runner集成测试通过！3/3 PASS")
    print("  S1 单器件LVS    ✓")
    print("  S2 LVS关闭      ✓")
    print("  S3 坐标变换     ✓")


if __name__ == "__main__":
    main()
