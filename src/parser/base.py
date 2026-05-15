"""网表解析器抽象基类。

所有格式的解析器都必须继承 NetlistParser 并实现 parse() 方法。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple, List

if TYPE_CHECKING:
    from .types import Component, Net


class NetlistParser(ABC):
    """网表解析器抽象基类。"""

    @abstractmethod
    def parse(self, path: str | Path) -> Tuple[List["Component"], List["Net"]]:
        """解析网表文件。

        Args:
            path: 网表文件路径

        Returns:
            (components, nets) — 器件列表和网络列表
        """

    @staticmethod
    @abstractmethod
    def format_name() -> str:
        """返回格式名称，如 'kicad', 'spectre', 'spice'。"""

    def get_component_by_ref(
        self, components: List["Component"], reference: str
    ) -> Optional["Component"]:
        """按 reference 查找器件（公共方法）。"""
        for c in components:
            if c.reference == reference:
                return c
        return None
