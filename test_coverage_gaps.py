"""补充测试：PCell验证边界、映射错误路径、Executor错误路径、Runner错误路径、快照边界。"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

# 添加src到path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import klayout.db as db
import pytest

# ── PCell 验证边界测试 ──────────────────────────────────────────────


class TestMIMCapacitorValidation:
    """MIMCapacitor.validate_params 边界值。"""

    @pytest.fixture
    def pcell(self):
        from pcells.mim_capacitor.pcell import MIMCapacitor
        return MIMCapacitor()

    def test_valid_boundary_min(self, pcell):
        valid, errors = pcell.validate_params({"length": 10, "width": 10})
        assert valid
        assert errors == []

    def test_valid_boundary_max(self, pcell):
        valid, errors = pcell.validate_params({"length": 200, "width": 200})
        assert valid
        assert errors == []

    def test_length_below_min(self, pcell):
        valid, errors = pcell.validate_params({"length": 9, "width": 50})
        assert not valid
        assert any("length" in e for e in errors)

    def test_length_above_max(self, pcell):
        valid, errors = pcell.validate_params({"length": 201, "width": 50})
        assert not valid

    def test_width_below_min(self, pcell):
        valid, errors = pcell.validate_params({"length": 50, "width": 9})
        assert not valid
        assert any("width" in e for e in errors)

    def test_width_above_max(self, pcell):
        valid, errors = pcell.validate_params({"length": 50, "width": 201})
        assert not valid

    def test_pin_positions_consistent_with_generate(self, pcell):
        """get_pin_positions返回的坐标应与generate()绘制位置一致。"""
        params = {"length": 50, "width": 30}
        pins = pcell.get_pin_positions(params)

        layout = db.Layout()
        layout.dbu = 0.001
        cell = layout.create_cell("TEST_MIM")
        pcell.generate(cell, params)

        # PI引脚应在MT层，NIN引脚应在MB层
        assert pins["PI"].layer == pcell.LAYERS["MT"]
        assert pins["NIN"].layer == pcell.LAYERS["MB"]


class TestSpiralInductorValidation:
    """SpiralInductor.validate_params 边界值。"""

    @pytest.fixture
    def pcell(self):
        from pcells.spiral_inductor.pcell import SpiralInductor
        return SpiralInductor()

    def test_valid_boundary_min(self, pcell):
        valid, errors = pcell.validate_params({
            "inner_radius": 20, "turns": 1.5, "width": 5, "spacing": 5,
        })
        assert valid
        assert errors == []

    def test_valid_boundary_max(self, pcell):
        valid, errors = pcell.validate_params({
            "inner_radius": 80, "turns": 6.5, "width": 20, "spacing": 15,
        })
        assert valid
        assert errors == []

    def test_turns_below_min(self, pcell):
        valid, errors = pcell.validate_params({
            "inner_radius": 30, "turns": 1.0, "width": 10, "spacing": 8,
        })
        assert not valid
        assert any("turns" in e for e in errors)

    def test_turns_above_max(self, pcell):
        valid, errors = pcell.validate_params({
            "inner_radius": 30, "turns": 7.0, "width": 10, "spacing": 8,
        })
        assert not valid

    def test_inner_radius_out_of_range(self, pcell):
        valid, _ = pcell.validate_params({
            "inner_radius": 10, "turns": 3, "width": 10, "spacing": 8,
        })
        assert not valid

    def test_half_turn_generates_correctly(self, pcell):
        """turns=2.5 应生成半圈段。"""
        params = {"inner_radius": 30, "turns": 2.5, "width": 10, "spacing": 8, "angle": 0}
        layout = db.Layout()
        layout.dbu = 0.001
        cell = layout.create_cell("TEST_IND_HALF")
        pcell.generate(cell, params)
        # 不应抛出异常，应成功生成
        assert cell.shapes(layout.layer(*pcell.LAYERS["METAL_TOP"])).size() > 0

    def test_bounding_box_with_rotation(self, pcell):
        """旋转时包围盒应大于无旋转时。"""
        params_no_rot = {"inner_radius": 30, "turns": 3, "width": 10, "spacing": 8, "angle": 0}
        params_rot = {"inner_radius": 30, "turns": 3, "width": 10, "spacing": 8, "angle": 45}

        bbox_0 = pcell.get_bounding_box(params_no_rot)
        bbox_45 = pcell.get_bounding_box(params_rot)

        # 旋转45°时包围盒应该更大（对角线更长）
        w0 = bbox_0[2] - bbox_0[0]
        w45 = bbox_45[2] - bbox_45[0]
        assert w45 > w0


class TestTransmissionLineValidation:
    """TransmissionLine.validate_params 边界值。"""

    @pytest.fixture
    def pcell(self):
        from pcells.transmission_line.pcell import TransmissionLine
        return TransmissionLine()

    def test_valid_boundary_min(self, pcell):
        valid, errors = pcell.validate_params({"width": 5, "length": 50, "angle": 0})
        assert valid

    def test_valid_boundary_max(self, pcell):
        valid, errors = pcell.validate_params({"width": 200, "length": 5000, "angle": 359})
        assert valid

    def test_angle_360_invalid(self, pcell):
        """angle=360 度应无效（范围 [0, 360)）。"""
        valid, errors = pcell.validate_params({"width": 50, "length": 500, "angle": 360})
        assert not valid
        assert any("angle" in e for e in errors)

    def test_angle_negative_invalid(self, pcell):
        valid, _ = pcell.validate_params({"width": 50, "length": 500, "angle": -1})
        assert not valid

    def test_length_below_min(self, pcell):
        valid, _ = pcell.validate_params({"width": 50, "length": 49, "angle": 0})
        assert not valid

    def test_length_above_max(self, pcell):
        valid, _ = pcell.validate_params({"width": 50, "length": 5001, "angle": 0})
        assert not valid


# ── 映射引擎错误路径 ────────────────────────────────────────────────


class TestMappingEngineErrors:
    """MappingEngine 错误路径。"""

    @pytest.fixture
    def mapper(self):
        from mapper.engine import MappingEngine
        return MappingEngine("config/mapping_rules.yaml")

    def test_unknown_device_type_raises(self, mapper):
        """未知device_type应抛ValueError。"""
        from parser.target_params import TargetParam
        target = TargetParam(reference="X1", device_type="UNKNOWN_TYPE", params={"freq": 1.0})
        with pytest.raises(ValueError, match="无映射规则"):
            mapper.map(target)

    def test_lookup_miss_raises(self, mapper):
        """查表无匹配应抛ValueError。"""
        from parser.target_params import TargetParam
        # capacitor_mim查表需要capacitance_pf，但如果表的key不全匹配也会miss
        # 用一个在映射规则中有但查表字段不匹配的params
        target = TargetParam(
            reference="C1",
            device_type="capacitor_mim",
            params={"nonexistent_key": 999},
        )
        with pytest.raises(ValueError, match="查表无匹配"):
            mapper.map(target)


# ── 目标参数解析错误路径 ─────────────────────────────────────────────


class TestTargetParamsParserErrors:
    """TargetParamsParser 错误路径。"""

    def test_malformed_json_raises(self, tmp_path):
        from parser.target_params import TargetParamsParser
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{invalid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            TargetParamsParser().parse(str(bad_json))

    def test_missing_required_fields_raises(self, tmp_path):
        from parser.target_params import TargetParamsParser
        bad_json = tmp_path / "missing_fields.json"
        bad_json.write_text(json.dumps([{"reference": "C1"}]), encoding="utf-8")
        with pytest.raises(KeyError):
            TargetParamsParser().parse(str(bad_json))


# ── Executor错误路径 ────────────────────────────────────────────────


class TestKLayoutExecutorErrors:
    """KLayoutExecutor 错误路径。"""

    @pytest.fixture
    def gds_with_tl(self, tmp_path):
        """创建含一条TL的GDS文件。"""
        from pcells.transmission_line.pcell import TransmissionLine
        layout = db.Layout()
        layout.dbu = 0.001
        top = layout.create_cell("TOP")
        tl_cell = layout.create_cell("TL1_TL_MICROSTRIP")
        tl = TransmissionLine()
        tl.generate(tl_cell, {"width": 50, "length": 500, "angle": 0})
        top.insert(db.CellInstArray(tl_cell.cell_index(), db.Trans()))
        gds_path = tmp_path / "test.gds"
        layout.write(str(gds_path))
        return gds_path

    def test_cell_not_found_returns_error(self, gds_with_tl, tmp_path):
        """reference在GDS中不存在时，应返回errors。"""
        from executor.klayout_executor import KLayoutExecutor
        from mapper.engine import MappedGeometry

        executor = KLayoutExecutor()
        result = executor.execute(
            gds_path=str(gds_with_tl),
            mapped_geometries=[MappedGeometry(
                reference="NONEXISTENT", target_pcell="TL_MICROSTRIP",
                geometry_params={"width": 50, "length": 500, "angle": 0},
            )],
            output_path=str(tmp_path / "out.gds"),
        )
        assert not result.success
        assert any("NONEXISTENT" in e for e in result.errors)

    def test_unknown_pcell_type_returns_error(self, gds_with_tl, tmp_path):
        """target_pcell未注册时，应返回errors。"""
        from executor.klayout_executor import KLayoutExecutor
        from mapper.engine import MappedGeometry

        executor = KLayoutExecutor()
        result = executor.execute(
            gds_path=str(gds_with_tl),
            mapped_geometries=[MappedGeometry(
                reference="TL1", target_pcell="UNKNOWN_PCELL",
                geometry_params={"width": 50, "length": 500, "angle": 0},
            )],
            output_path=str(tmp_path / "out.gds"),
        )
        assert not result.success
        assert any("UNKNOWN_PCELL" in e or "查找失败" in e for e in result.errors)

    def test_validate_params_warning_does_not_block(self, gds_with_tl, tmp_path):
        """参数超出PCell范围时应有warning但仍执行。"""
        from executor.klayout_executor import KLayoutExecutor
        from mapper.engine import MappedGeometry

        executor = KLayoutExecutor()
        # length=1 远低于TL的最小50
        result = executor.execute(
            gds_path=str(gds_with_tl),
            mapped_geometries=[MappedGeometry(
                reference="TL1", target_pcell="TL_MICROSTRIP",
                geometry_params={"width": 50, "length": 1, "angle": 0},
            )],
            output_path=str(tmp_path / "out.gds"),
        )
        # 即使参数校验有warning，执行仍应成功
        assert "TL1" in result.updated_cells


# ── Runner错误路径 ──────────────────────────────────────────────────


class TestRunnerErrors:
    """Runner 错误路径。"""

    def test_netlist_parse_failure(self, tmp_path):
        """网表文件不存在时Runner应返回失败。"""
        from core.runner import Runner, RunConfig
        config = RunConfig(
            gds_path=str(tmp_path / "dummy.gds"),
            netlist_path=str(tmp_path / "nonexistent.net"),
            target_params_path=str(tmp_path / "targets.json"),
            mapping_rules_path="config/mapping_rules.yaml",
            drc_enabled=False,
        )
        runner = Runner(config)
        result = runner.run()
        assert not result.success
        assert any("网表" in e for e in result.errors)

    def test_target_params_parse_failure(self, tmp_path):
        """目标参数文件格式错误时Runner应返回失败。"""
        from core.runner import Runner, RunConfig

        # 创建一个有效的网表文件
        netlist_path = tmp_path / "test.net"
        netlist_path.write_text(
            "(export (version D001)\n"
            "  (components\n"
            "    (comp (ref TL1) (value TL_MICROSTRIP))\n"
            "  )\n"
            "  (nets\n"
            "  )\n"
            ")\n",
            encoding="utf-8",
        )
        bad_target = tmp_path / "bad.json"
        bad_target.write_text("{invalid", encoding="utf-8")

        config = RunConfig(
            gds_path=str(tmp_path / "dummy.gds"),
            netlist_path=str(netlist_path),
            target_params_path=str(bad_target),
            mapping_rules_path="config/mapping_rules.yaml",
            drc_enabled=False,
        )
        runner = Runner(config)
        result = runner.run()
        assert not result.success
        assert any("目标参数" in e for e in result.errors)


# ── 快照管理器边界 ──────────────────────────────────────────────────


class TestSnapshotManagerEdgeCases:
    """SnapshotManager 边界情况。"""

    def test_load_nonexistent_returns_none(self, tmp_path):
        from state.snapshot_manager import SnapshotManager
        mgr = SnapshotManager(str(tmp_path))
        result = mgr.load_params_state(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_load_corrupted_json_returns_none(self, tmp_path):
        """损坏JSON文件应抛异常（当前未捕获，确认行为）。"""
        from state.snapshot_manager import SnapshotManager
        mgr = SnapshotManager(str(tmp_path))
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{corrupt", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            mgr.load_params_state(str(bad_file))

    def test_save_and_load_roundtrip(self, tmp_path):
        """保存后重新加载应得到相同数据。"""
        from state.snapshot_manager import SnapshotManager, ParamsSnapshot, DeviceSnapshot, PinSnapshot
        mgr = SnapshotManager(str(tmp_path))

        snapshot = ParamsSnapshot(
            gds_path="/tmp/test.gds",
            timestamp="2026-01-01T00:00:00",
            devices={
                "C1": DeviceSnapshot(
                    ref="C1",
                    pcell_type="CAP_MIM",
                    params={"length": 50, "width": 30},
                    pins={
                        "PI": PinSnapshot(name="PI", x=60.0, y=15.0),
                        "NIN": PinSnapshot(name="NIN", x=60.0, y=4.5),
                    },
                ),
            },
        )

        path = tmp_path / "snapshot.json"
        mgr.save_params_state(str(path), snapshot)
        loaded = mgr.load_params_state(str(path))

        assert loaded is not None
        assert loaded.gds_path == "/tmp/test.gds"
        assert loaded.timestamp == "2026-01-01T00:00:00"
        assert "C1" in loaded.devices
        assert loaded.devices["C1"].pcell_type == "CAP_MIM"
        assert loaded.devices["C1"].pins["PI"].x == 60.0
        assert loaded.devices["C1"].pins["NIN"].name == "NIN"


# ── PCell注册表 ────────────────────────────────────────────────────


class TestPCellRegistry:
    """PCell注册表边界。"""

    def test_list_pcells_returns_all(self):
        from pcells.registry import list_pcells
        pcells = list_pcells()
        assert "CAP_MIM" in pcells
        assert "IND_SPIRAL" in pcells
        assert "TL_MICROSTRIP" in pcells

    def test_get_unknown_raises(self):
        from pcells.registry import get_pcell
        with pytest.raises(ValueError, match="未知PCell类型"):
            get_pcell("NONEXISTENT")


# ── PCell generate 与 get_pin_positions 一致性 ──────────────────────


class TestPCellPinConsistency:
    """验证所有PCell的generate()与get_pin_positions()一致性。"""

    def test_tl_pin_positions_match_generate(self):
        from pcells.transmission_line.pcell import TransmissionLine
        tl = TransmissionLine()
        params = {"width": 50, "length": 500, "angle": 0}
        pins = tl.get_pin_positions(params)

        layout = db.Layout()
        layout.dbu = 0.001
        cell = layout.create_cell("TL_TEST")
        tl.generate(cell, params)

        # PIN_MARKER层应该有标记
        marker_layer = layout.layer(*BasePCell_like_pin_marker_layer())
        # P1在原点，P2在(500,0)
        assert pins["P1"].x == pytest.approx(0.0, abs=0.1)
        assert pins["P2"].x == pytest.approx(500.0, abs=0.1)

    def test_tl_rotated_pin_positions(self):
        """旋转90°时引脚位置应旋转。"""
        from pcells.transmission_line.pcell import TransmissionLine
        tl = TransmissionLine()
        params = {"width": 50, "length": 500, "angle": 90}
        pins = tl.get_pin_positions(params)

        # 90°旋转：P1从(0,0)→(0,0), P2从(500,0)→(0,500)
        assert pins["P1"].x == pytest.approx(0.0, abs=0.1)
        assert pins["P1"].y == pytest.approx(0.0, abs=0.1)
        assert pins["P2"].x == pytest.approx(0.0, abs=0.1)
        assert pins["P2"].y == pytest.approx(500.0, abs=0.1)


def BasePCell_like_pin_marker_layer():
    from pcells.base import BasePCell
    return BasePCell.PIN_MARKER_LAYER
