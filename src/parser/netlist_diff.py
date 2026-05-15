"""网表差异比较器。

对比原始网表和修改后网表，找出 value 变化的器件。
只支持修改已有器件的值，不支持器件的增减。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from .kicad_netlist import Component

logger = logging.getLogger(__name__)


@dataclass
class DeviceDiff:
    """单个器件的差异。"""
    reference: str           # 器件引用名，如 "C1"
    part_name: str           # 器件类型，如 "CAP_MIM"
    old_value: str           # 原始值，如 "1pF"
    new_value: str           # 修改后值，如 "2pF"


@dataclass
class NetlistDiffResult:
    """网表差异结果。"""
    changed: List[DeviceDiff] = field(default_factory=list)  # 值变化的器件
    errors: List[str] = field(default_factory=list)          # 错误（如器件增减）

    @property
    def has_changes(self) -> bool:
        return len(self.changed) > 0


def diff_netlists(
    original_components: List[Component],
    modified_components: List[Component],
) -> NetlistDiffResult:
    """对比两个网表的器件列表，找出差异。

    Args:
        original_components: 原始网表器件列表
        modified_components: 修改后网表器件列表

    Returns:
        NetlistDiffResult
    """
    result = NetlistDiffResult()

    # 构建 ref → component 映射
    orig_by_ref: Dict[str, Component] = {c.reference: c for c in original_components}
    mod_by_ref: Dict[str, Component] = {c.reference: c for c in modified_components}

    # 检查器件增减
    added = set(mod_by_ref.keys()) - set(orig_by_ref.keys())
    removed = set(orig_by_ref.keys()) - set(mod_by_ref.keys())

    if added:
        result.errors.append(f"新增器件（暂不支持）: {sorted(added)}")
    if removed:
        result.errors.append(f"删除器件（暂不支持）: {sorted(removed)}")

    # 比较共有器件的 value 变化
    common_refs = set(orig_by_ref.keys()) & set(mod_by_ref.keys())
    for ref in sorted(common_refs):
        orig = orig_by_ref[ref]
        mod = mod_by_ref[ref]

        # 检查器件类型是否变化
        if orig.name != mod.name:
            result.errors.append(
                f"器件 {ref} 类型变更（暂不支持）: {orig.name} → {mod.name}"
            )
            continue

        if orig.value != mod.value:
            result.changed.append(DeviceDiff(
                reference=ref,
                part_name=mod.name,
                old_value=orig.value,
                new_value=mod.value,
            ))
            logger.info(f"器件变更: {ref} {orig.name} '{orig.value}' → '{mod.value}'")

    if not result.has_changes and not result.errors:
        logger.info("网表无差异，无需更新")

    return result
