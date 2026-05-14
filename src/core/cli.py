"""CLI入口点。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from core.runner import Runner, RunConfig
from parser.kicad_netlist import KiCadNetlistParser
from parser.target_params import TargetParamsParser
from mapper.engine import MappingEngine, MappedGeometry
from executor.klayout_executor import KLayoutExecutor
from state.snapshot_manager import SnapshotManager, ParamsSnapshot, DeviceSnapshot, PinSnapshot
from routing.types import PinState


def cmd_init(args: argparse.Namespace) -> None:
    """从初始参数生成初版GDS和参数快照（冷启动）。"""
    import klayout.db as db
    import time

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("pam.init")

    # 解析网表获取网络信息
    netlist_parser = KiCadNetlistParser()
    components, nets = netlist_parser.parse(args.netlist)
    logger.info(f"网表解析: {len(components)} 器件, {len(nets)} 网络")

    # 解析初始参数
    target_parser = TargetParamsParser()
    targets = target_parser.parse(args.params)
    logger.info(f"初始参数: {len(targets)} 个器件")

    # 映射
    mapper = MappingEngine(args.rules)
    from pcells.registry import get_pcell
    mapped: list[MappedGeometry] = []
    for t in targets:
        mg = mapper.map(t)
        mapped.append(mg)
        logger.info(f"  {mg.reference} → {mg.target_pcell}: {mg.geometry_params}")

    # 生成初版GDS
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    layout = db.Layout()
    layout.dbu = 0.001  # 1nm resolution
    top = layout.create_cell("L_MATCH")

    for mg in mapped:
        pcell = get_pcell(mg.target_pcell)
        cell_name = f"{mg.reference}_{mg.target_pcell}"
        cell = layout.create_cell(cell_name)
        pcell.generate(cell, mg.geometry_params)
        top.insert(db.CellInstArray(cell.cell_index(), db.Trans(db.Point(0, 0))))
        logger.info(f"  已生成: {cell_name}")

    layout.write(str(output_path))
    logger.info(f"初版GDS已生成: {output_path}")

    # 生成并保存参数快照
    state_dir = Path(args.state_dir)
    snapshot_mgr = SnapshotManager(state_dir)
    params_path = state_dir / "params_snapshot.json"

    devices: dict[str, DeviceSnapshot] = {}
    for mg in mapped:
        try:
            pcell = get_pcell(mg.target_pcell)
            pin_positions = pcell.get_pin_positions(mg.geometry_params)
            pins = {
                pin_name: PinSnapshot(name=pin_name, x=pos.x, y=pos.y)
                for pin_name, pos in pin_positions.items()
            }
            devices[mg.reference] = DeviceSnapshot(
                ref=mg.reference,
                pcell_type=mg.target_pcell,
                params=mg.geometry_params,
                pins=pins,
            )
        except Exception as e:
            logger.warning(f"无法获取{mg.reference}的引脚位置: {e}")

    snapshot = ParamsSnapshot(
        gds_path=str(output_path),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        devices=devices,
    )
    snapshot_mgr.save_params_state(params_path, snapshot)
    logger.info(f"参数快照已保存: {params_path}")

    print(f"\n[PAM Init 完成]")
    print(f"  初版GDS: {output_path}")
    print(f"  参数快照: {params_path}")
    print(f"\n后续迭代命令:")
    print(f"  pam run --gds {output_path} --netlist {args.netlist} \\")
    print(f"    --target <new_params.json> --output <updated.gds>")
    print(f"\n参数快照记录了所有器件的当前params和pins，")
    print(f"下次迭代时StretchRouter将据此执行实际连线拉伸。")


def cmd_run(args: argparse.Namespace) -> None:
    """执行迭代优化。"""
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = RunConfig(
        gds_path=args.gds,
        netlist_path=args.netlist,
        target_params_path=args.target,
        mapping_rules_path=args.rules,
        output_path=args.output,
        state_dir=args.state_dir,
        history_path=args.history,
        stretch_threshold_dbu=10000,
    )

    runner = Runner(config)
    result = runner.run()

    if result.success:
        print(f"\nSUCCESS: 版图更新完成 → {result.execution_result.output_path}")
        print(f"  更新器件: {result.execution_result.updated_cells}")
        if result.execution_result.stretch_result:
            sr = result.execution_result.stretch_result
            print(f"  连线: 拉伸 {len(sr.stretched)} 条, 断线 {len(sr.broken)} 条")
        print(f"  耗时: {result.duration_s:.2f}s")
    else:
        print(f"\nFAILED: 版图更新失败")
        for err in result.errors:
            print(f"  - {err}")
        sys.exit(1)


def main() -> None:
    """PAM工具CLI入口。"""
    parser = argparse.ArgumentParser(
        description="PAM Layout Iteration Automation Engine"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # init 子命令：从初始参数生成初版GDS
    p_init = subparsers.add_parser("init", help="生成初版GDS和参数快照（冷启动）")
    p_init.add_argument("--gds", help="模板GDS路径（可为空文件占位）")
    p_init.add_argument("--netlist", required=True, help="KiCad网表文件路径")
    p_init.add_argument("--params", required=True, help="初始参数JSON文件路径")
    p_init.add_argument("--rules", default="config/mapping_rules.yaml", help="映射规则YAML路径")
    p_init.add_argument("--output", required=True, help="输出GDS文件路径")
    p_init.add_argument("--state-dir", default="state", help="状态目录")

    # run 子命令：执行迭代优化
    p_run = subparsers.add_parser("run", help="执行版图迭代优化")
    p_run.add_argument("--gds", required=True, help="输入GDS文件路径")
    p_run.add_argument("--netlist", required=True, help="KiCad网表文件路径")
    p_run.add_argument("--target", required=True, help="目标参数JSON文件路径")
    p_run.add_argument("--rules", default="config/mapping_rules.yaml", help="映射规则YAML路径")
    p_run.add_argument("--output", default="output.gds", help="输出GDS文件路径")
    p_run.add_argument("--state-dir", default="state", help="状态目录")
    p_run.add_argument("--history", default="state/history.jsonl", help="历史记录文件路径")
    p_run.add_argument("--verbose", "-v", action="store_true", help="详细日志")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
