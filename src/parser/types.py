"""公共数据类：所有网表格式通用的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Component:
    """网表中的器件（格式无关的公共表示）。"""
    reference: str  # 如 C1, L1
    value: str     # 如 2pF
    name: str      # 器件类型名，如 CAP_MIM
    lib: str = ""  # 器件库来源（KiCad 特有，部分格式有）
    ext: dict = field(default_factory=dict)  # 格式特有字段，如 KiCad 的 footprint


@dataclass
class Net:
    """网络连接信息（格式无关的公共表示）。"""
    name: str  # 网络名，如 NET_C1_TL1
    nodes: list[tuple[str, str]] = field(default_factory=list)  # [(ref, pin_name), ...]
    ext: dict = field(default_factory=dict)  # 格式特有字段
