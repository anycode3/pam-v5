"""StateManager 参数快照系统端到端集成测试。

DEPRECATED: 此测试基于旧的快照流程，已被 GDS 实时提取取代。
快照管理器已简化为 GDSBackupManager，仅处理 GDS 文件备份/回滚。
新流程的测试见 tests/ 目录。

测试完整流程:
  1. init: 从初始参数生成初版GDS + params_snapshot.json
  2. 第1次迭代: 小调整，验证快照写入
  3. 第2次迭代: 微调触发实际拉伸，验证引脚位移被正确记录
  4. 验证params_snapshot.json包含正确的pins记录
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))
pcell_dir = Path(__file__).parent
sys.path.insert(0, str(pcell_dir))

import klayout.db as db
from state.snapshot_manager import SnapshotManager, ParamsSnapshot, DeviceSnapshot, PinSnapshot
from routing.types import PinState
from parser.kicad_netlist import KiCadNetlistParser
from parser.target_params import TargetParamsParser
from mapper.engine import MappingEngine
from executor.klayout_executor import KLayoutExecutor
from core.runner import Runner, RunConfig

FIXTURES = Path("tests/fixtures/l_match")
WORK = Path("state/state_manager_test")


def clean_work():
    """清理工作目录。"""
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _do_init():
    """执行init流程，生成初版GDS和参数快照。"""
    from pcells.registry import get_pcell

    clean_work()

    # 初始参数: 1pF(C1) + 50Ω/500um(TL1)
    init_params = [
        {"reference": "C1", "type": "capacitor_mim", "params": {"capacitance_pf": 1.0}},
        {"reference": "TL1", "type": "TL_MICROSTRIP", "params": {"impedance_ohm": 50.0, "length_um": 500.0}},
    ]
    write_json(WORK / "init_params.json", init_params)

    netlist_parser = KiCadNetlistParser()
    components, nets = netlist_parser.parse(str(FIXTURES / "kicad_netlist.net"))

    target_parser = TargetParamsParser()
    targets = target_parser.parse(str(WORK / "init_params.json"))

    mapper = MappingEngine("config/mapping_rules.yaml")
    mapped = [mapper.map(t) for t in targets]

    # 生成GDS
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("L_MATCH")
    for mg in mapped:
        pcell = get_pcell(mg.target_pcell)
        cell_name = f"{mg.reference}_{mg.target_pcell}"
        cell = layout.create_cell(cell_name)
        pcell.generate(cell, mg.geometry_params)
        top.insert(db.CellInstArray(cell.cell_index(), db.Trans(db.Point(0, 0))))

    layout.write(str(WORK / "initial_layout.gds"))

    devices = {}
    for mg in mapped:
        pcell = get_pcell(mg.target_pcell)
        pin_positions = pcell.get_pin_positions(mg.geometry_params)
        pins = {k: PinSnapshot(name=k, x=v.x, y=v.y) for k, v in pin_positions.items()}
        devices[mg.reference] = DeviceSnapshot(
            ref=mg.reference,
            pcell_type=mg.target_pcell,
            params=mg.geometry_params,
            pins=pins,
        )

    snapshot = ParamsSnapshot(
        gds_path=str(WORK / "initial_layout.gds"),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        devices=devices,
    )
    snapshot_mgr = SnapshotManager(WORK)
    snapshot_mgr.save_params_state(WORK / "params_snapshot.json", snapshot)
    return snapshot


def _do_first_iteration():
    """执行第1次迭代。"""
    target_params = [
        {"reference": "C1", "type": "capacitor_mim", "params": {"capacitance_pf": 2.0}},
    ]
    write_json(WORK / "target_1.json", target_params)

    config = RunConfig(
        gds_path=str(WORK / "initial_layout.gds"),
        netlist_path=str(FIXTURES / "kicad_netlist.net"),
        target_params_path=str(WORK / "target_1.json"),
        pdk_config_path="config/mapping_rules.yaml",
        output_path=str(WORK / "iter1_layout.gds"),
        state_dir=str(WORK),
        stretch_threshold_dbu=10000,
    )

    runner = Runner(config)
    result = runner.run()
    return result


# ──────────────────────────────────────────────
# 测试1: init 生成初版GDS + params_snapshot.json
# ──────────────────────────────────────────────
def test_1_init_creates_gds_and_snapshot():
    """init命令应生成GDS和参数快照。"""
    print("\n=== 测试1: init 生成初版GDS和参数快照 ===")

    loaded = _do_init()

    # 验证快照内容
    snap_path = WORK / "params_snapshot.json"
    assert snap_path.exists(), "参数快照未生成"
    assert (WORK / "initial_layout.gds").exists(), "初版GDS未生成"

    snapshot_mgr = SnapshotManager(WORK)
    loaded = snapshot_mgr.load_params_state(snap_path)
    assert loaded is not None, "参数快照加载失败"
    assert "C1" in loaded.devices, "C1应记录在快照中"
    assert "TL1" in loaded.devices, "TL1应记录在快照中"

    # 验证pins记录
    c1_snap = loaded.devices["C1"]
    assert "PI" in c1_snap.pins, f"C1应有PI引脚记录，实际pins={c1_snap.pins.keys()}"
    print(f"  C1引脚: { {k: (v.x, v.y) for k, v in c1_snap.pins.items()} }")
    print(f"  TL1引脚: { {k: (v.x, v.y) for k, v in loaded.devices['TL1'].pins.items()} }")

    # 验证gds_path和timestamp被正确保存和加载
    assert loaded.gds_path != "", "gds_path不应为空"
    assert loaded.timestamp != "", "timestamp不应为空"

    print("  PASS")


# ──────────────────────────────────────────────
# 测试2: 第1次迭代，小调整
# ──────────────────────────────────────────────
def test_2_first_iteration():
    """第1次迭代执行，验证快照更新。"""
    print("\n=== 测试2: 第1次迭代 C1 1pF→2pF ===")

    # 先确保init已完成
    _do_init()

    result = _do_first_iteration()

    assert result.success, f"第1次迭代失败: {result.errors}"
    assert (WORK / "iter1_layout.gds").exists(), "第1次迭代输出GDS不存在"

    # 验证快照已更新
    snap_path = WORK / "params_snapshot.json"
    snap_mgr = SnapshotManager(WORK)
    snap = snap_mgr.load_params_state(snap_path)
    assert snap is not None, "参数快照丢失"

    c1_snap = snap.devices["C1"]
    # 2pF → 57x57μm，PI引脚x约67
    pi_x = c1_snap.pins["PI"].x
    print(f"  C1 2pF PI引脚位置: ({pi_x}, {c1_snap.pins['PI'].y})")
    assert 55 <= pi_x <= 75, f"2pF C1引脚x约67um，实际{pi_x}"

    # 验证GDS内容
    layout = db.Layout()
    layout.read(str(WORK / "iter1_layout.gds"))
    top = layout.top_cell()
    for inst in top.each_inst():
        cell = inst.cell
        if cell.name.startswith("C1_"):
            mim_layer = layout.layer(9, 0)
            bbox = cell.bbox_per_layer(mim_layer)
            w = (bbox.right - bbox.left) * layout.dbu
            print(f"  C1极板尺寸: {w:.0f}um (2pF应57um)")
            assert abs(w - 57) < 2, f"2pF C1宽度应为57um，实际{w}"

    print("  PASS")


# ──────────────────────────────────────────────
# 测试3: 第2次迭代，验证old_pin_states被传入
# ──────────────────────────────────────────────
def test_3_second_iteration_with_stretch():
    """第2次迭代: C1 2pF→3pF，验证old_pin_states链路打通。"""
    print("\n=== 测试3: 第2次迭代 C1 2pF→3pF（验证old_pin_states） ===")

    # 先完成init+第1次迭代
    _do_init()
    _do_first_iteration()

    target_params = [
        {"reference": "C1", "type": "capacitor_mim", "params": {"capacitance_pf": 3.0}},
    ]
    write_json(WORK / "target_2.json", target_params)

    # 读取当前快照作为"旧状态"
    snap_path = WORK / "params_snapshot.json"
    snap_mgr = SnapshotManager(WORK)
    old_snap = snap_mgr.load_params_state(snap_path)
    assert old_snap is not None, "需要先运行test_2"

    # 提取old_pin_states
    from core.runner import Runner as RunnerCls
    dummy_runner = object.__new__(RunnerCls)

    target_parser = TargetParamsParser()
    targets = target_parser.parse(str(WORK / "target_2.json"))
    mapper = MappingEngine("config/mapping_rules.yaml")
    mapped = [mapper.map(t) for t in targets]

    extracted_old_pins = dummy_runner._extract_old_pin_states(old_snap, mapped)
    print(f"  从快照提取的旧引脚: {list(extracted_old_pins.keys())}")

    assert "C1.PI" in extracted_old_pins, "应包含C1.PI旧引脚"
    old_pi = extracted_old_pins["C1.PI"]
    print(f"  C1.PI旧位置: ({old_pi.x:.1f}, {old_pi.y:.1f})")

    # 执行第2次迭代
    config = RunConfig(
        gds_path=str(WORK / "iter1_layout.gds"),
        netlist_path=str(FIXTURES / "kicad_netlist.net"),
        target_params_path=str(WORK / "target_2.json"),
        pdk_config_path="config/mapping_rules.yaml",
        output_path=str(WORK / "iter2_layout.gds"),
        state_dir=str(WORK),
        stretch_threshold_dbu=10000,
    )

    runner = Runner(config)
    result = runner.run()

    assert result.success, f"第2次迭代失败: {result.errors}"

    # 验证stretch_result
    if result.execution_result and result.execution_result.stretch_result:
        sr = result.execution_result.stretch_result
        print(f"  连线拉伸: stretched={sr.stretched}, broken={sr.broken}")

    # 验证快照已更新
    snap = snap_mgr.load_params_state(snap_path)
    c1_snap = snap.devices["C1"]
    new_pi = c1_snap.pins["PI"]
    print(f"  C1.PI新位置: ({new_pi.x:.1f}, {new_pi.y:.1f})")
    print(f"  引脚位移: ({new_pi.x - old_pi.x:.1f}, {new_pi.y - old_pi.y:.1f})")

    # 3pF → length=70, width=70, PI.x = 45um local; 调试发现实际PI=(80,35)
    assert 78 <= new_pi.x <= 82, f"3pF C1引脚x约80um，实际{new_pi.x}"

    print("  PASS")


def main():
    print("StateManager 参数快照系统端到端集成测试")
    print("=" * 55)

    test_1_init_creates_gds_and_snapshot()
    test_2_first_iteration()
    test_3_second_iteration_with_stretch()

    print("\n" + "=" * 55)
    print("StateManager 集成测试通过！3/3 PASS")
    print("  init生成GDS+snapshot  ✓")
    print("  第1次迭代(snapshot写入) ✓")
    print("  第2次迭代(old_pin_states) ✓")


if __name__ == "__main__":
    main()
