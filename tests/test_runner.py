"""Runner 单元测试。

测试 Runner 的数据类和核心方法（不依赖真实 GDS 文件的方法）。
"""

import pytest

from src.core.runner import Runner, RunConfig, RunResult, ExecutionResult


class TestExecutionResult:
    """ExecutionResult 数据类。"""

    def test_success(self):
        result = ExecutionResult(success=True, updated_cells=["C1"])
        assert result.success
        assert result.updated_cells == ["C1"]
        assert result.errors == []

    def test_failure_with_errors(self):
        result = ExecutionResult(
            success=False,
            updated_cells=[],
            errors=["器件未找到"],
        )
        assert not result.success
        assert len(result.errors) == 1

    def test_with_output_path(self):
        result = ExecutionResult(
            success=True,
            updated_cells=["C1"],
            output_path="/tmp/output.gds",
        )
        assert result.output_path == "/tmp/output.gds"


class TestRunConfig:
    """RunConfig 数据类。"""

    def test_defaults(self):
        config = RunConfig(
            gds_path="input.gds",
            netlist_path="orig.net",
            modified_netlist_path="mod.net",
            mapping_rules_path="rules.yaml",
        )
        assert config.output_path == "output.gds"
        assert config.state_dir == "state"
        assert config.drc_enabled is True
        assert config.lvs_enabled is False
        assert config.drc_max_retries == 3
        assert config.drc_shrink_factor == 0.9

    def test_custom_values(self):
        config = RunConfig(
            gds_path="a.gds",
            netlist_path="b.net",
            modified_netlist_path="c.net",
            mapping_rules_path="d.yaml",
            output_path="out.gds",
            state_dir="custom_state",
            drc_enabled=False,
            lvs_enabled=True,
        )
        assert config.output_path == "out.gds"
        assert config.state_dir == "custom_state"
        assert not config.drc_enabled
        assert config.lvs_enabled


class TestRunResult:
    """RunResult 数据类。"""

    def test_default_values(self):
        result = RunResult(success=True)
        assert result.success
        assert result.diff_result is None
        assert result.errors == []
        assert result.duration_s == 0.0
        assert result.drc_retries == 0


class TestRunnerConstruction:
    """Runner 构造。"""

    def test_creates_with_drc_enabled(self):
        config = RunConfig(
            gds_path="test.gds",
            netlist_path="orig.net",
            modified_netlist_path="mod.net",
            mapping_rules_path="config/mapping_rules.yaml",
            drc_enabled=True,
        )
        runner = Runner(config)
        assert runner._drc_runner is not None
        assert runner._lvs_runner is None

    def test_creates_with_lvs_enabled(self):
        config = RunConfig(
            gds_path="test.gds",
            netlist_path="orig.net",
            modified_netlist_path="mod.net",
            mapping_rules_path="config/mapping_rules.yaml",
            drc_enabled=False,
            lvs_enabled=True,
        )
        runner = Runner(config)
        assert runner._drc_runner is None
        assert runner._lvs_runner is not None

    def test_creates_with_backup_manager(self):
        config = RunConfig(
            gds_path="test.gds",
            netlist_path="orig.net",
            modified_netlist_path="mod.net",
            mapping_rules_path="config/mapping_rules.yaml",
        )
        runner = Runner(config)
        assert runner._backup_mgr is not None


class TestRunnerHelperMethods:
    """Runner 辅助方法。"""

    def _make_runner(self):
        config = RunConfig(
            gds_path="test.gds",
            netlist_path="orig.net",
            modified_netlist_path="mod.net",
            mapping_rules_path="config/mapping_rules.yaml",
        )
        return Runner(config)

    def test_find_affected_nets(self):
        runner = self._make_runner()

        from src.parser.kicad_netlist import Net
        nets = [
            Net(name="NET1", nodes=[("C1", "PI"), ("L1", "P1")]),
            Net(name="NET2", nodes=[("C2", "PI"), ("L1", "P2")]),
            Net(name="NET3", nodes=[("C3", "PI"), ("C4", "NIN")]),
        ]

        affected = runner._find_affected_nets(nets, ["C1"])
        assert "NET1" in affected
        assert "NET2" not in affected
        assert "NET3" not in affected

    def test_find_affected_nets_multiple_refs(self):
        runner = self._make_runner()

        from src.parser.kicad_netlist import Net
        nets = [
            Net(name="NET1", nodes=[("C1", "PI"), ("L1", "P1")]),
            Net(name="NET2", nodes=[("C2", "PI"), ("L1", "P2")]),
            Net(name="NET3", nodes=[("C3", "PI"), ("C4", "NIN")]),
        ]

        affected = runner._find_affected_nets(nets, ["C1", "C2"])
        assert "NET1" in affected
        assert "NET2" in affected
        assert "NET3" not in affected
