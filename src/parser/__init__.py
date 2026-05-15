"""网表解析模块。

支持多种网表格式：
- kicad: KiCad S-expression 格式（默认）
- spice: SPICE 格式（预留）
- spectre: Spectre 格式（预留）

用法:
    from src.parser import NetlistRouter
    components, nets = NetlistRouter.parse("design.net")

    # 或直接使用特定格式解析器
    from src.parser import KiCadNetlistParser
    parser = KiCadNetlistParser()
    components, nets = parser.parse("design.net")
"""

from .types import Component, Net
from .base import NetlistParser
from .factory import NetlistRouter, register_parser
from .exceptions import (
    NetlistParseError,
    UnsupportedFormatError,
    FormatDetectionError,
)

# 向后兼容：直接从 kicad_netlist 导入仍可用
from .kicad_netlist import KiCadNetlistParser

__all__ = [
    # 公共数据类
    "Component",
    "Net",
    # 抽象基类
    "NetlistParser",
    # 工厂
    "NetlistRouter",
    "register_parser",
    # 异常
    "NetlistParseError",
    "UnsupportedFormatError",
    "FormatDetectionError",
    # 向后兼容
    "KiCadNetlistParser",
]
