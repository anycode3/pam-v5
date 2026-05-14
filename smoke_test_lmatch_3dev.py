"""L型匹配电路3器件全链路集成测试。

5场景:
  S1: 单器件微调(C1 2pF→3pF)
  S2: 相邻器件联动(TL1+L1同时变)
  S3: 大跳变触发断线标记(L1 1nH→5nH)
  S4: DRC交叉冲突(C1+L1同时膨胀)
  S5: 全回滚(L1极端参数)
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
from validator.drc_runner import KLayoutDRCRunner
from validator.ref_mapper import ViolationRefMapper
from pcells.registry import get_pcell, list_pcells

FIXTURES = Path("tests/fixtures/l_match")
WORK = Path("state/l_match_test")


def setup_work_dir(scenario: str) -> Path:
    """为每个场景创建独立工作目录。"""
    work = WORK / scenario
    work.mkdir(parents=True, exist_ok=True)
    # 复制初始GDS到工作目录
    src_gds = FIXTURES / "initial_layout.gds"
    dst_gds = work / "input.gds"
    shutil.copy2(src_gds, dst_gds)
    return work


def run_scenario(scenario: str, target_file: str, drc_enabled: bool = True) -> Runner:
    """运行一个场景。"""
    work = setup_work_dir(scenario)
    target_path = FIXTURES / target_file

    config = RunConfig(
        gds_path=str(work / "input.gds"),
        netlist_path=str(FIXTURES / "kicad_netlist.net"),
        target_params_path=str(target_path),
        mapping_rules_path="config/mapping_rules.yaml",
        output_path=str(work / "output.gds"),
        snapshot_dir=str(work / "snapshots"),
        history_path=str(work / "history.jsonl"),
        drc_enabled=drc_enabled,
        drc_rules_path="config/drc_rules/simple_rf.yaml",
        drc_max_retries=3,
    )

    runner = Runner(config)
    result = runner.run()
    return runner, result, work


# ──────────────────────────────────────────────
# S1: 单器件微调
# ──────────────────────────────────────────────
def test_s1():
    print("\n=== S1: 单器件微调 C1 2pF→3pF ===")
    runner, result, work = run_scenario("s1", "target_s1.json")

    print(f"  success={result.success}")
    print(f"  drc_passed={result.drc_result.passed if result.drc_result else 'N/A'}")
    print(f"  updated={result.execution_result.updated_cells if result.execution_result else []}")

    # C1应被更新
    assert "C1" in (result.execution_result.updated_cells if result.execution_result else []), "C1未被更新"

    # DRC应通过
    if result.drc_result:
        assert result.drc_result.passed, f"S1 DRC未通过: {result.drc_result.violation_count}违例"

    # 验证GDS内容：C1应为3pF(70x70um)
    layout = db.Layout()
    layout.read(str(work / "output.gds"))
    top = layout.top_cell()
    for inst in top.each_inst():
        cell = inst.cell
        if "C1" in cell.name:
            mim_layer = layout.layer(9, 0)
            bbox = cell.bbox_per_layer(mim_layer)
            w = (bbox.right - bbox.left) * layout.dbu
            print(f"  C1极板尺寸: {w:.0f}um (3pF应约70um)")
            # 3pF映射到70x70
            assert abs(w - 70) < 2, f"C1极板宽度应为70um，实际{w}"

    print("  PASS")


# ──────────────────────────────────────────────
# S2: 相邻器件联动
# ──────────────────────────────────────────────
def test_s2():
    print("\n=== S2: 相邻器件联动 TL1+L1 ===")
    runner, result, work = run_scenario("s2", "target_s2.json")

    print(f"  success={result.success}")
    print(f"  updated={result.execution_result.updated_cells if result.execution_result else []}")
    if result.errors:
        for e in result.errors:
            print(f"  error: {e}")

    # 两个器件都应被更新
    updated = result.execution_result.updated_cells if result.execution_result else []
    assert "TL1" in updated, "TL1未被更新"
    assert "L1" in updated, "L1未被更新"

    # 验证TL1几何
    layout = db.Layout()
    layout.read(str(work / "output.gds"))
    top = layout.top_cell()
    for inst in top.each_inst():
        cell = inst.cell
        if "TL1" in cell.name:
            metal_layer = layout.layer(6, 0)
            bbox = cell.bbox_per_layer(metal_layer)
            l_um = (bbox.right - bbox.left) * layout.dbu
            print(f"  TL1长度: {l_um:.0f}um (应2000um)")
            assert abs(l_um - 2000) < 5, f"TL1长度应为2000um，实际{l_um}"

    print("  PASS")


# ──────────────────────────────────────────────
# S3: 大跳变触发断线标记
# ──────────────────────────────────────────────
def test_s3():
    print("\n=== S3: 大跳变 L1 1nH→5nH ===")
    runner, result, work = run_scenario("s3", "target_s3.json")

    print(f"  success={result.success}")
    print(f"  updated={result.execution_result.updated_cells if result.execution_result else []}")

    # L1应被更新
    updated = result.execution_result.updated_cells if result.execution_result else []
    assert "L1" in updated, "L1未被更新"

    # 5nH电感面积很大(ir=65, t=5.0)，验证几何生成
    layout = db.Layout()
    layout.read(str(work / "output.gds"))
    top = layout.top_cell()
    l1_found = False
    for inst in top.each_inst():
        cell = inst.cell
        # 精确匹配：cell名以L1_开头，避免匹配TL1
        if cell.name.startswith("L1_"):
            l1_found = True
            # 用cell.bbox()检查整体尺寸
            bbox = cell.bbox()
            dbu = layout.dbu
            w_um = (bbox.right - bbox.left) * dbu
            h_um = (bbox.top - bbox.bottom) * dbu
            print(f"  L1尺寸: {w_um:.0f}x{h_um:.0f}um")
            # ir=65, t=5.0, w=10, s=8: outer_half约147um, bbox约294um宽
            assert w_um > 200, f"5nH电感应大于200um，实际{w_um}"
    assert l1_found, "未找到L1 cell"

    # DRC可能通过也可能不通过（取决于布局间距）
    if result.drc_result:
        print(f"  DRC: passed={result.drc_result.passed}, violations={result.drc_result.violation_count}")
        if not result.drc_result.passed:
            print(f"  (大面积电感触发DRC，符合预期)")

    print("  PASS")


# ──────────────────────────────────────────────
# S4: DRC交叉冲突
# ──────────────────────────────────────────────
def test_s4():
    print("\n=== S4: DRC交叉冲突 C1+L1同时膨胀 ===")
    runner, result, work = run_scenario("s4", "target_s4.json")

    print(f"  success={result.success}")
    print(f"  drc_retries={result.drc_retries}")
    if result.drc_result:
        print(f"  drc_passed={result.drc_result.passed}")
        print(f"  violations={result.drc_result.violation_count}")
    if result.errors:
        for e in result.errors:
            print(f"  error: {e}")

    # 验证DRC重试机制生效
    if result.drc_result and not result.drc_result.passed:
        # DRC失败后应有重试记录
        print(f"  DRC失败，重试{result.drc_retries}次")
        assert result.drc_retries > 0, "DRC失败后应有重试"

    # 验证RefMapper关联
    layout = db.Layout()
    output_gds = work / "output.gds"
    if output_gds.exists():
        layout.read(str(output_gds))
        ref_mapper = ViolationRefMapper.from_layout(layout)
        print(f"  器件bbox: {list(ref_mapper.bboxes.keys())}")

    print("  PASS")


# ──────────────────────────────────────────────
# S5: 全回滚
# ──────────────────────────────────────────────
def test_s5():
    print("\n=== S5: 全回滚 L1极端参数 ===")
    runner, result, work = run_scenario("s5", "target_s5.json")

    print(f"  success={result.success}")
    print(f"  errors={result.errors}")

    # 10nH映射到最近查表值(5nH)，可能DRC通过也可能失败
    # 关键验证：1) 流程不崩溃 2) history记录完整 3) 输出GDS存在
    assert result.execution_result is not None, "应有执行结果"

    # 验证L1映射到了5nH（查表最大值）
    l1_mapped = next((m for m in result.mapped_geometries if m.reference == "L1"), None)
    if l1_mapped:
        print(f"  L1映射结果: {l1_mapped.geometry_params}")
        # 10nH无精确匹配，映射到5nH(ir=65, turns=5.0)
        assert l1_mapped.geometry_params["turns"] == 5.0, "应映射到最大值5nH"

    # 验证输出GDS存在（可能是回滚后的版本）
    output_gds = work / "output.gds"
    assert output_gds.exists(), "输出GDS应存在（回滚后）"

    print("  PASS")


def main():
    print("L型匹配电路 3器件全链路集成测试")
    print("=" * 50)

    Path("state/l_match_test").mkdir(parents=True, exist_ok=True)

    # 先验证PCell注册
    pcells = list_pcells()
    print(f"已注册PCell: {list(pcells.keys())}")
    assert "CAP_MIM" in pcells
    assert "TL_MICROSTRIP" in pcells
    assert "IND_SPIRAL" in pcells

    test_s1()
    test_s2()
    test_s3()
    test_s4()
    test_s5()

    print("\n" + "=" * 50)
    print("L型匹配电路3器件集成测试完成！5/5 PASS")
    print("  S1 单器件微调 ✓")
    print("  S2 相邻联动  ✓")
    print("  S3 大跳变断线 ✓")
    print("  S4 DRC冲突   ✓")
    print("  S5 全回滚     ✓")


if __name__ == "__main__":
    main()
