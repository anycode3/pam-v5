"""CLI入口点。"""

import argparse
import logging
import sys

from src.core.runner import Runner, RunConfig


def cmd_run(args: argparse.Namespace) -> None:
    """执行版图迭代优化。"""
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = RunConfig(
        gds_path=args.gds,
        netlist_path=args.netlist,
        modified_netlist_path=args.modified_netlist,
        mapping_rules_path=args.rules,
        output_path=args.output,
        state_dir=args.state_dir,
        history_path=args.history,
        drc_enabled=not args.no_drc,
        lvs_enabled=args.lvs,
    )

    runner = Runner(config)
    result = runner.run()

    if result.success:
        print(f"\nSUCCESS: 版图更新完成 → {result.execution_result.output_path}")
        if result.diff_result:
            for d in result.diff_result.changed:
                print(f"  变更: {d.reference} '{d.old_value}' → '{d.new_value}'")
        if result.execution_result:
            print(f"  更新器件: {result.execution_result.updated_cells}")
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

    # run 子命令
    p_run = subparsers.add_parser("run", help="执行版图迭代优化")
    p_run.add_argument("--gds", required=True, help="输入GDS文件路径")
    p_run.add_argument("--netlist", required=True, help="原始KiCad网表文件路径")
    p_run.add_argument("--modified-netlist", required=True, help="修改后KiCad网表文件路径")
    p_run.add_argument("--rules", default="config/mapping_rules.yaml", help="映射规则YAML路径")
    p_run.add_argument("--output", default="output.gds", help="输出GDS文件路径")
    p_run.add_argument("--state-dir", default="state", help="状态目录")
    p_run.add_argument("--history", default="state/history.jsonl", help="历史记录文件路径")
    p_run.add_argument("--no-drc", action="store_true", help="跳过DRC验证")
    p_run.add_argument("--lvs", action="store_true", help="启用LVS验证")
    p_run.add_argument("--verbose", "-v", action="store_true", help="详细日志")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
