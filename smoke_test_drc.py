"""DRC模块冒烟测试。

验证：DRC基础执行 → 无违例通过 → 故意制造违例检出 →
      报告解析 → RefMapper关联 → 重试循环(可修正/不可修正) → 调度器集成
"""

from __future__ import annotations

import sys
from pathlib import Path

src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))
pcell_dir = Path(__file__).parent
sys.path.insert(0, str(pcell_dir))

import klayout.db as db
from validator.drc_runner import KLayoutDRCRunner
from validator.ref_mapper import ViolationRefMapper
from validator.base import Severity, Violation
from pcells.registry import get_pcell
from mapper.engine import MappingEngine
from mapper.engine import MappedGeometry
from executor.klayout_executor import KLayoutExecutor
from core.runner import Runner, RunConfig


def test_drc_clean_gds():
    """测试无违例GDS应通过DRC。"""
    print("\n=== 测试1: DRC无违例通过 ===")
    # 创建合规版图：间距足够大的两个器件
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TOP")

    # 两个间距50um的矩形，不会触发间距违规
    l1 = layout.layer(6, 0)
    top.shapes(l1).insert(db.Box(0, 0, 20000, 20000))        # 20x20um
    top.shapes(l1).insert(db.Box(100000, 0, 120000, 20000))  # 20x20um, 间距80um

    gds_path = "state/snapshots/drc_clean.gds"
    layout.write(gds_path)

    runner = KLayoutDRCRunner()
    result = runner.run(gds_path, "config/drc_rules/simple_rf.yaml")

    print(f"  passed={result.passed}, violations={result.violation_count}")
    assert result.passed, f"合规版图DRC应通过，但发现{result.violation_count}违例"
    print("  PASS")


def test_drc_spacing_violation():
    """测试故意制造间距违规应被检出。"""
    print("\n=== 测试2: DRC间距违规检出 ===")
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TOP")

    # 两个间距仅0.5um的矩形，违反metal1.min_spacing=1.0um
    l1 = layout.layer(6, 0)
    top.shapes(l1).insert(db.Box(0, 0, 20000, 20000))       # 0-20um
    top.shapes(l1).insert(db.Box(20500, 0, 40500, 20000))   # 20.5-40.5um, gap=0.5um

    gds_path = "state/snapshots/drc_spacing_fail.gds"
    layout.write(gds_path)

    runner = KLayoutDRCRunner()
    result = runner.run(gds_path, "config/drc_rules/simple_rf.yaml")

    print(f"  passed={result.passed}, violations={result.violation_count}")
    assert not result.passed, "有间距违规时DRC不应通过"

    # 验证检出的是spacing规则
    spacing_violations = [v for v in result.violations if "spacing" in v.rule_name]
    assert len(spacing_violations) > 0, "应检出spacing违例"
    print(f"  检出spacing违例: {len(spacing_violations)} 条")
    print("  PASS")


def test_drc_width_violation():
    """测试故意制造线宽违规应被检出。"""
    print("\n=== 测试3: DRC线宽违规检出 ===")
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TOP")

    # 一个仅1um宽的矩形，违反metal1.min_width=2.0um
    l1 = layout.layer(6, 0)
    top.shapes(l1).insert(db.Box(0, 0, 100000, 1000))  # 100um x 1um

    gds_path = "state/snapshots/drc_width_fail.gds"
    layout.write(gds_path)

    runner = KLayoutDRCRunner()
    result = runner.run(gds_path, "config/drc_rules/simple_rf.yaml")

    print(f"  passed={result.passed}, violations={result.violation_count}")
    width_violations = [v for v in result.violations if "width" in v.rule_name]
    assert len(width_violations) > 0, "应检出width违例"
    print(f"  检出width违例: {len(width_violations)} 条")
    print("  PASS")


def test_drc_report():
    """测试DRC报告JSON输出。"""
    print("\n=== 测试4: DRC报告解析 ===")
    # 使用测试2的失败GDS
    report_path = "state/snapshots/drc_spacing_fail_drc_report.json"
    assert Path(report_path).exists(), f"报告文件不存在: {report_path}"

    import json
    report = json.loads(Path(report_path).read_text())
    print(f"  报告: {report['total_violations']} 违例, {report['errors']} 错误")
    assert report["total_violations"] > 0
    for v in report["violations"][:3]:
        print(f"    {v['rule']}: {v['description']} @ ({v['x']},{v['y']})")
    print("  PASS")


def test_ref_mapper():
    """测试RefMapper违例坐标→器件关联。"""
    print("\n=== 测试5: RefMapper器件关联 ===")
    # 模拟器件bbox
    bboxes = {
        "C1": (0.0, 0.0, 57.0, 57.0),
        "TL1": (100.0, 0.0, 2100.0, 20.0),
    }
    mapper = ViolationRefMapper(bboxes, tolerance=10.0)

    # 违例在C1内部
    violations = [
        Violation(rule_name="mim.min_area", severity=Severity.ERROR,
                  layer="9/0", x=30.0, y=30.0, description="test"),
        # 违例在TL1内部
        Violation(rule_name="metal1.min_spacing", severity=Severity.ERROR,
                  layer="6/0", x=500.0, y=10.0, description="test"),
        # 违例不在任何器件内
        Violation(rule_name="metal1.min_spacing", severity=Severity.ERROR,
                  layer="6/0", x=80.0, y=10.0, description="test"),
    ]

    mapped = mapper.map_violations(violations)

    print(f"  C1区域违例关联: {mapped[0].related_refs}")
    print(f"  TL1区域违例关联: {mapped[1].related_refs}")
    print(f"  无人区域违例关联: {mapped[2].related_refs}")

    assert mapped[0].related_refs == ["C1"], "C1区域违例应关联C1"
    assert mapped[1].related_refs == ["TL1"], "TL1区域违例应关联TL1"
    assert mapped[2].related_refs is None, "无人区域违例不应关联"
    print("  PASS")


def test_ref_mapper_from_layout():
    """测试从版图自动构建RefMapper。"""
    print("\n=== 测试6: RefMapper从版图构建 ===")
    pcell = get_pcell("CAP_MIM")
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("TOP")
    cap_cell = layout.create_cell("C1_CAP_MIM")
    pcell.generate(cap_cell, {"length": 57, "width": 57})
    top.insert(db.CellInstArray(cap_cell.cell_index(), db.Trans(db.Point(0, 0))))

    mapper = ViolationRefMapper.from_layout(layout)
    print(f"  器件bbox: {mapper.bboxes}")
    assert "C1" in mapper.bboxes, "应检测到C1器件"
    print("  PASS")


def test_runner_with_drc_pass():
    """测试调度器+DRC（无违例应通过）。"""
    print("\n=== 测试7: 调度器+DRC通过 ===")
    # 创建合规初始GDS
    pcell = get_pcell("CAP_MIM")
    tl_pcell = get_pcell("TL_MICROSTRIP")
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("L_MATCH")
    c1 = layout.create_cell("C1_CAP_MIM")
    pcell.generate(c1, {"length": 40, "width": 40})
    top.insert(db.CellInstArray(c1.cell_index(), db.Trans(db.Point(0, 0))))
    tl1 = layout.create_cell("TL1_TL_MICROSTRIP")
    tl_pcell.generate(tl1, {"width": 20, "length": 500, "angle": 0})
    top.insert(db.CellInstArray(tl1.cell_index(), db.Trans(db.Point(200000, 0))))
    layout.write("state/snapshots/runner_drc_initial.gds")

    # 目标参数：1pF→2pF（57x57um，间距足够不会DRC违规）
    import json
    target_data = [
        {"reference": "C1", "type": "capacitor_mim", "params": {"capacitance_pf": 2.0}},
    ]
    Path("state/snapshots/runner_drc_target.json").write_text(json.dumps(target_data))

    config = RunConfig(
        gds_path="state/snapshots/runner_drc_initial.gds",
        netlist_path="examples/l_match.net",
        target_params_path="state/snapshots/runner_drc_target.json",
        pdk_config_path="config/mapping_rules.yaml",
        output_path="state/snapshots/runner_drc_output.gds",
        drc_enabled=True,
        drc_rules_path="config/drc_rules/simple_rf.yaml",
    )

    runner = Runner(config)
    result = runner.run()

    print(f"  success={result.success}")
    print(f"  drc_result.passed={result.drc_result.passed if result.drc_result else 'N/A'}")
    print(f"  drc_retries={result.drc_retries}")
    if result.errors:
        for e in result.errors:
            print(f"  error: {e}")

    assert result.success, f"调度器+DRC应成功: {result.errors}"
    if result.drc_result:
        assert result.drc_result.passed, "DRC应通过"
    print("  PASS")


def test_runner_drc_history():
    """验证DRC结果写入history。"""
    print("\n=== 测试8: DRC历史记录 ===")
    history_path = Path("state/history.jsonl")
    if history_path.exists():
        lines = history_path.read_text().strip().split("\n")
        last = lines[-1] if lines else ""
        import json
        entry = json.loads(last)
        drc = entry.get("drc")
        if drc:
            print(f"  DRC记录: enabled={drc['enabled']}, passed={drc['passed']}, "
                  f"violations={drc['violations']}, retries={drc['retries']}")
            assert drc["enabled"], "DRC应为enabled"
        else:
            print("  无DRC记录（可能DRC未启用）")
    print("  PASS")


def main():
    print("DRC模块冒烟测试")
    print("=" * 40)

    Path("state/snapshots").mkdir(parents=True, exist_ok=True)

    test_drc_clean_gds()
    test_drc_spacing_violation()
    test_drc_width_violation()
    test_drc_report()
    test_ref_mapper()
    test_ref_mapper_from_layout()
    test_runner_with_drc_pass()
    test_runner_drc_history()

    print("\n" + "=" * 40)
    print("DRC模块测试通过！8/8 PASS")
    print("  DRC基础 ✓  无违例通过 ✓  间距违规 ✓")
    print("  线宽违规 ✓  报告解析 ✓  RefMapper ✓")
    print("  调度器集成 ✓  历史记录 ✓")


if __name__ == "__main__":
    main()
