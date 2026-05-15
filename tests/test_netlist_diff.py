"""netlist_diff 单元测试。"""

import pytest

from src.parser.kicad_netlist import Component
from src.parser.netlist_diff import diff_netlists, DeviceDiff, NetlistDiffResult


def _make_comp(ref: str, name: str, value: str) -> Component:
    """快速构造 Component。"""
    return Component(reference=ref, name=name, value=value, lib="test_lib")


class TestDiffNetlistsNoChanges:
    """网表无差异。"""

    def test_identical_netlists(self):
        orig = [_make_comp("C1", "CAP_MIM", "1pF")]
        mod = [_make_comp("C1", "CAP_MIM", "1pF")]
        result = diff_netlists(orig, mod)
        assert not result.has_changes
        assert result.errors == []

    def test_empty_netlists(self):
        result = diff_netlists([], [])
        assert not result.has_changes
        assert result.errors == []


class TestDiffNetlistsValueChanged:
    """值变化检测。"""

    def test_single_value_change(self):
        orig = [_make_comp("C1", "CAP_MIM", "1pF")]
        mod = [_make_comp("C1", "CAP_MIM", "2pF")]
        result = diff_netlists(orig, mod)
        assert result.has_changes
        assert len(result.changed) == 1
        assert result.changed[0] == DeviceDiff(
            reference="C1",
            part_name="CAP_MIM",
            old_value="1pF",
            new_value="2pF",
        )

    def test_multiple_value_changes(self):
        orig = [
            _make_comp("C1", "CAP_MIM", "1pF"),
            _make_comp("L1", "IND_SPIRAL", "1nH"),
        ]
        mod = [
            _make_comp("C1", "CAP_MIM", "2pF"),
            _make_comp("L1", "IND_SPIRAL", "2nH"),
        ]
        result = diff_netlists(orig, mod)
        assert len(result.changed) == 2
        refs = {d.reference for d in result.changed}
        assert refs == {"C1", "L1"}

    def test_mixed_changed_and_unchanged(self):
        orig = [
            _make_comp("C1", "CAP_MIM", "1pF"),
            _make_comp("C2", "CAP_MIM", "5pF"),
            _make_comp("L1", "IND_SPIRAL", "1nH"),
        ]
        mod = [
            _make_comp("C1", "CAP_MIM", "2pF"),
            _make_comp("C2", "CAP_MIM", "5pF"),
            _make_comp("L1", "IND_SPIRAL", "3nH"),
        ]
        result = diff_netlists(orig, mod)
        assert len(result.changed) == 2
        refs = {d.reference for d in result.changed}
        assert refs == {"C1", "L1"}


class TestDiffNetlistsPartNameChange:
    """器件类型变更（不支持，应报错）。"""

    def test_part_name_changed(self):
        orig = [_make_comp("C1", "CAP_MIM", "1pF")]
        mod = [_make_comp("C1", "IND_SPIRAL", "1nH")]
        result = diff_netlists(orig, mod)
        assert any("类型变更" in e for e in result.errors)
        # 不应记录为 value 变化
        assert not result.has_changes

    def test_part_name_unchanged_value_changed(self):
        """类型未变但值变化 — 正常检测。"""
        orig = [_make_comp("C1", "CAP_MIM", "1pF")]
        mod = [_make_comp("C1", "CAP_MIM", "2pF")]
        result = diff_netlists(orig, mod)
        assert result.has_changes
        assert not result.errors


class TestDiffNetlistsDeviceAddRemove:
    """器件增减（不支持，应报错）。"""

    def test_device_added(self):
        orig = [_make_comp("C1", "CAP_MIM", "1pF")]
        mod = [
            _make_comp("C1", "CAP_MIM", "1pF"),
            _make_comp("C2", "CAP_MIM", "2pF"),
        ]
        result = diff_netlists(orig, mod)
        assert any("新增器件" in e for e in result.errors)

    def test_device_removed(self):
        orig = [
            _make_comp("C1", "CAP_MIM", "1pF"),
            _make_comp("C2", "CAP_MIM", "2pF"),
        ]
        mod = [_make_comp("C1", "CAP_MIM", "1pF")]
        result = diff_netlists(orig, mod)
        assert any("删除器件" in e for e in result.errors)

    def test_both_added_and_removed(self):
        orig = [_make_comp("C1", "CAP_MIM", "1pF")]
        mod = [_make_comp("C2", "CAP_MIM", "2pF")]
        result = diff_netlists(orig, mod)
        assert any("新增器件" in e for e in result.errors)
        assert any("删除器件" in e for e in result.errors)


class TestNetlistDiffResult:
    """NetlistDiffResult 属性。"""

    def test_has_changes_true(self):
        result = NetlistDiffResult(
            changed=[DeviceDiff("C1", "CAP_MIM", "1pF", "2pF")]
        )
        assert result.has_changes

    def test_has_changes_false(self):
        result = NetlistDiffResult()
        assert not result.has_changes
