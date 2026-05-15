#!/usr/bin/env python3
"""从 KiCad 网表生成初始 GDS 版图。

用法:
    python scripts/generate_initial_gds.py examples/l_match.net output.gds

该脚本将网表中的每个器件实例化为对应的 PCell，
然后根据网表连接关系在 top cell 上绘制初始连线。

输出 GDS 结构:
    TOP (top cell)           ← 连线画在这里
      ├── C1_CAP_MIM (inst)
      ├── L1_IND_SPIRAL (inst)
      └── TL1_TL_MICROSTRIP (inst)
"""

import sys
import argparse
from pathlib import Path

# 添加 src 和 pcells 到 path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import klayout.db as db

from src.parser.kicad_netlist import KiCadNetlistParser
from src.parser.value_parser import parse_value, value_to_device_type
from src.parser.target_params import TargetParam
from src.mapper.engine import MappingEngine
from src.routing.initial_router import InitialRouter, draw_wire_segments


def generate_initial_gds(
    netlist_path: str,
    output_path: str,
    mapping_rules_path: str = "config/mapping_rules.yaml",
    wire_width: float = 10.0,
) -> None:
    """从网表生成初始 GDS。

    Args:
        netlist_path: KiCad 网表文件路径
        output_path: 输出 GDS 文件路径
        mapping_rules_path: 映射规则 YAML 路径
        wire_width: 连线宽度 (um)
    """
    # 解析网表
    parser = KiCadNetlistParser()
    components, nets = parser.parse(netlist_path)
    print(f"解析网表: {len(components)} 器件, {len(nets)} 网络")

    # 映射引擎
    mapper = MappingEngine(mapping_rules_path)

    # 构建 ref → pcell/params 映射
    ref_to_pcell: dict = {}
    ref_to_params: dict = {}

    for comp in components:
        part_name = comp.name
        try:
            params = parse_value(part_name, comp.value)
            device_type = value_to_device_type(part_name)
            target = TargetParam(
                reference=comp.reference,
                device_type=device_type,
                params=params,
            )
            mg = mapper.map(target)
            ref_to_pcell[comp.reference] = mg.target_pcell
            ref_to_params[comp.reference] = mg.geometry_params
            print(f"  {comp.reference}: {part_name} '{comp.value}' → {mg.target_pcell} {mg.geometry_params}")
        except Exception as e:
            print(f"  警告: 无法映射 {comp.reference} ({part_name} '{comp.value}'): {e}")

    # 创建 GDS layout
    layout = db.Layout()
    layout.dbu = 0.001  # 1nm DBU

    # 导入 PCell 注册表
    from pcells.registry import _auto_register
    _auto_register()

    # 获取 PCell
    from pcells.registry import get_pcell

    # 创建 top cell
    top = layout.create_cell("TOP")

    # 为每个器件创建子 cell 并放置 instance
    instance_positions: dict = {}
    x_offset = 0.0
    y_offset = 0.0

    for comp in components:
        ref = comp.reference
        if ref not in ref_to_pcell:
            continue

        pcell_name = ref_to_pcell[ref]
        params = ref_to_params[ref]

        # 创建子 cell
        cell = layout.create_cell(f"{ref}_{pcell_name}")

        # 获取 PCell 并生成几何
        pcell = get_pcell(pcell_name)
        pcell.generate(cell, params)

        # 在 top cell 中放置 instance（简单的网格排列）
        col = len([c for c in components if c.reference < comp.reference])
        row = col // 4
        col = col % 4
        dx = int(x_offset + col * 3000 / layout.dbu)
        dy = int(y_offset + row * 3000 / layout.dbu)
        trans = db.Trans(dx, dy)

        top.insert(db.CellInstArray(cell.cell_index(), trans))
        instance_positions[ref] = (dx * layout.dbu, dy * layout.dbu)
        print(f"  放置 {ref} @ ({dx * layout.dbu:.1f}, {dy * layout.dbu:.1f})")

    # 初始布线
    router = InitialRouter()
    wires = router.route_all(
        layout=layout,
        top_cell=top,
        nets=nets,
        ref_to_pcell=ref_to_pcell,
        ref_to_params=ref_to_params,
        wire_width=wire_width,
    )

    for net_name, wire_list in wires.items():
        draw_wire_segments(top, layout, wire_list)
        print(f"  布线 {net_name}: {len(wire_list)} 段")

    # 保存
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    layout.write(str(output))
    print(f"GDS 已保存: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 KiCad 网表生成初始 GDS 版图"
    )
    parser.add_argument("netlist", help="KiCad 网表文件路径")
    parser.add_argument("output", help="输出 GDS 文件路径")
    parser.add_argument(
        "--rules",
        default="config/mapping_rules.yaml",
        help="映射规则 YAML 路径 (默认: config/mapping_rules.yaml)",
    )
    parser.add_argument(
        "--wire-width",
        type=float,
        default=10.0,
        help="连线宽度 um (默认: 10.0)",
    )

    args = parser.parse_args()

    # 切换到项目根目录
    project_root = Path(__file__).parent.parent
    import os
    os.chdir(project_root)

    generate_initial_gds(
        netlist_path=args.netlist,
        output_path=args.output,
        mapping_rules_path=args.rules,
        wire_width=args.wire_width,
    )


if __name__ == "__main__":
    main()
