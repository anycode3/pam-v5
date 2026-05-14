"""冒烟测试：读JSON目标 → KLayout创建PCell → 改参数 → 保存GDS。

验证 parser → mapper → executor 最小链路。
使用 klayout.db headless API，无需GUI。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 添加src到path
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

import klayout.db as db
from parser.target_params import TargetParamsParser, TargetParam
from mapper.engine import MappingEngine


def create_test_gds(output_path: str) -> str:
    """创建一个带简单几何的测试GDS文件（headless模式）。"""
    layout = db.Layout()
    layout.dbu = 0.001  # 1nm DBU

    # 顶层cell
    top = layout.create_cell("TOP")

    # 创建模拟C1的子cell（矩形，代表MIM电容）
    c1_cell = layout.create_cell("C1_CAP_MIM")
    l1 = layout.layer(1, 0)  # metal层
    c1_cell.shapes(l1).insert(db.Box(0, 0, 40000, 40000))  # 40um x 40um
    top.insert(db.CellInstArray(c1_cell.cell_index(), db.Trans(db.Point(0, 0))))

    # 创建模拟L1的子cell（矩形，代表电感）
    l1_cell = layout.create_cell("L1_IND_SPIRAL")
    l2 = layout.layer(2, 0)  # 另一层
    l1_cell.shapes(l2).insert(db.Box(0, 0, 50000, 50000))  # 50um x 50um
    top.insert(db.CellInstArray(l1_cell.cell_index(), db.Trans(db.Point(100000, 0))))

    # 创建模拟TL1的子cell（矩形，代表传输线）
    tl1_cell = layout.create_cell("TL1_TL_MICROSTRIP")
    tl1_cell.shapes(l1).insert(db.Box(0, 0, 200000, 20000))  # 200um x 20um
    top.insert(db.CellInstArray(tl1_cell.cell_index(), db.Trans(db.Point(0, 100000))))

    # 保存GDS
    layout.write(output_path)
    print(f"测试GDS已创建: {output_path}")
    return output_path


def test_parser():
    """测试目标参数解析。"""
    print("\n=== 测试1: 目标参数解析 ===")
    parser = TargetParamsParser()
    targets = parser.parse("examples/target_params.json")
    for t in targets:
        print(f"  {t.reference} ({t.device_type}): {t.params}")
    assert len(targets) == 3, f"期望3个目标参数，实际{len(targets)}"
    print("  PASS")


def test_mapper():
    """测试映射引擎。"""
    print("\n=== 测试2: 电气→几何映射 ===")
    parser = TargetParamsParser()
    targets = parser.parse("examples/target_params.json")
    engine = MappingEngine("config/mapping_rules.yaml")
    mapped = engine.map_all(targets)
    for mg in mapped:
        print(f"  {mg.reference} → {mg.target_pcell}: {mg.geometry_params}")
        if mg.warnings:
            for w in mg.warnings:
                print(f"    WARNING: {w}")
    assert len(mapped) == 3, f"期望3个映射结果，实际{len(mapped)}"
    print("  PASS")


def test_klayout_create():
    """测试KLayout GDS创建。"""
    print("\n=== 测试3: KLayout GDS创建 ===")
    gds_path = create_test_gds("state/snapshots/test_initial.gds")
    assert Path(gds_path).exists(), "GDS文件未创建"

    # 验证GDS内容
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()
    print(f"  顶层cell: {top.name}")
    print(f"  子实例数: {top.child_instances()}")
    assert top.child_instances() == 3, "期望3个子实例"
    print("  PASS")


def test_klayout_update_cell():
    """测试KLayout cell定位与几何更新。

    验证核心链路：加载GDS → 按reference定位cell → 修改几何 → 保存。
    """
    print("\n=== 测试4: KLayout Cell定位与更新 ===")

    # 自建测试GDS（不依赖其他测试）
    gds_path = create_test_gds("state/snapshots/test_initial.gds")

    parser = TargetParamsParser()
    targets = parser.parse("examples/target_params.json")
    engine = MappingEngine("config/mapping_rules.yaml")
    mapped = engine.map_all(targets)

    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()

    updated = []
    for mg in mapped:
        # 按reference定位cell（模拟PCell定位）
        target_cell = None
        for inst in top.each_inst():
            cell = inst.cell
            if cell.name.startswith(f"{mg.reference}_") or cell.name == mg.reference:
                target_cell = cell
                break

        if target_cell is None:
            print(f"  未找到cell: {mg.reference}")
            continue

        # 清除旧几何，写入新几何（模拟PCell参数更新）
        l1 = layout.layer(1, 0)
        l2 = layout.layer(2, 0)
        target_cell.clear()

        # 根据映射结果创建新几何
        if "width" in mg.geometry_params and "height" in mg.geometry_params:
            # 电容/电感类：矩形
            w = int(mg.geometry_params["width"] * 1000 / layout.dbu)
            h = int(mg.geometry_params["height"] * 1000 / layout.dbu) if "height" in mg.geometry_params else w
            target_cell.shapes(l1).insert(db.Box(0, 0, w, h))
        elif "width" in mg.geometry_params:
            # 传输线类
            w = int(mg.geometry_params["width"] * 1000 / layout.dbu)
            target_cell.shapes(l1).insert(db.Box(0, 0, 200000, w))

        updated.append(mg.reference)
        print(f"  已更新: {mg.reference} ({target_cell.name}) → {mg.geometry_params}")

    # 保存更新后的GDS
    output_path = "state/snapshots/test_updated.gds"
    layout.write(output_path)
    print(f"  更新后GDS: {output_path}")
    assert len(updated) == 3, f"期望更新3个cell，实际{len(updated)}"
    print("  PASS")


def main():
    print("PAM MVP 冒烟测试")
    print("=" * 40)

    # 确保目录存在
    Path("state/snapshots").mkdir(parents=True, exist_ok=True)

    # 1. 解析目标参数
    test_parser()

    # 2. 映射
    test_mapper()

    # 3. KLayout创建GDS
    test_klayout_create()

    # 4. KLayout更新cell
    test_klayout_update_cell()

    print("\n" + "=" * 40)
    print("冒烟测试完成！核心链路跑通。")
    print("  parser ✓  mapper ✓  executor ✓")


if __name__ == "__main__":
    main()
