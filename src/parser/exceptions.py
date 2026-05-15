"""网表解析相关异常类。"""

from __future__ import annotations


class NetlistParseError(Exception):
    """网表解析错误基类。"""
    pass


class UnsupportedFormatError(NetlistParseError):
    """不支持的网表格式。"""

    def __init__(self, path: str, supported: list[str]):
        self.path = path
        self.supported = supported
        super().__init__(
            f"无法解析网表文件: {path}，不支持的格式。"
            f"支持的格式: {', '.join(supported)}"
        )


class FormatDetectionError(NetlistParseError):
    """无法自动检测网表格式。"""

    def __init__(self, path: str):
        self.path = path
        super().__init__(
            f"无法识别网表格式: {path}，请显式指定 --netlist-format"
        )
