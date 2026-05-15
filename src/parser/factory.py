"""网表解析器工厂：自动检测格式并路由到对应解析器。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Type, Tuple, List

from .base import NetlistParser
from .types import Component, Net
from .exceptions import UnsupportedFormatError, FormatDetectionError

logger = logging.getLogger(__name__)

# 格式 → 解析器类的注册表
_FORMAT_REGISTRY: Dict[str, Type[NetlistParser]] = {}


def register_parser(format_name: str):
    """解析器注册装饰器。

    用法:
        @register_parser("kicad")
        class KiCadNetlistParser(NetlistParser):
            ...
    """
    def decorator(cls: Type[NetlistParser]) -> Type[NetlistParser]:
        _FORMAT_REGISTRY[format_name] = cls
        logger.debug(f"注册网表解析器: {format_name} -> {cls.__name__}")
        return cls
    return decorator


def _detect_format(path: str | Path) -> str:
    """根据文件扩展名 + 文件头内容检测格式。

    Args:
        path: 网表文件路径

    Returns:
        格式名称字符串

    Raises:
        FormatDetectionError: 无法自动检测格式时抛出
    """
    p = Path(path)

    # 1. 按扩展名判断
    ext_map = {
        ".net": "kicad",
        ".sexp": "kicad",
        ".cir": "spice",
        ".spectre": "spectre",
    }
    if p.suffix.lower() in ext_map:
        fmt = ext_map[p.suffix.lower()]
        logger.debug(f"按扩展名检测格式: {path} -> {fmt}")
        return fmt

    # 2. 读文件头判断
    try:
        with open(p, "rb") as f:
            header = f.read(500)
        if b"export" in header and b"version" in header:
            logger.debug(f"按文件头检测格式: {path} -> kicad")
            return "kicad"
        # SPICE 通常以 * 注释行开头，或包含 .model/.subckt 等关键词
        if header.startswith(b"*") or (b".model" in header.lower() and b"+" not in header[:3]):
            logger.debug(f"按文件头检测格式: {path} -> spice")
            return "spice"
        if b"begin" in header.lower():
            logger.debug(f"按文件头检测格式: {path} -> spectre")
            return "spectre"
    except Exception as e:
        logger.warning(f"读取文件头失败: {path}: {e}")

    raise FormatDetectionError(str(path))


class NetlistRouter:
    """网表解析器工厂，根据格式自动路由。"""

    @staticmethod
    def parse(path: str | Path) -> Tuple[List[Component], List[Net]]:
        """自动检测格式并解析。

        Args:
            path: 网表文件路径

        Returns:
            (components, nets)

        Raises:
            FormatDetectionError: 无法自动检测格式
            UnsupportedFormatError: 格式不支持
        """
        fmt = _detect_format(path)
        parser_cls = _FORMAT_REGISTRY.get(fmt)
        if parser_cls is None:
            raise UnsupportedFormatError(str(path), list(_FORMAT_REGISTRY.keys()))
        logger.info(f"解析网表: {path} (格式: {fmt})")
        return parser_cls().parse(path)

    @staticmethod
    def for_format(fmt: str) -> NetlistParser:
        """显式指定格式获取解析器实例。

        Args:
            fmt: 格式名称，如 'kicad'

        Returns:
            NetlistParser 实例

        Raises:
            UnsupportedFormatError: 格式不支持
        """
        parser_cls = _FORMAT_REGISTRY.get(fmt)
        if parser_cls is None:
            raise UnsupportedFormatError(str(fmt), list(_FORMAT_REGISTRY.keys()))
        return parser_cls()

    @staticmethod
    def supported_formats() -> List[str]:
        """返回已注册的格式列表。"""
        return list(_FORMAT_REGISTRY.keys())
