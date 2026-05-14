"""PCell注册表：名字→类映射，executor通过名字查找PCell实现。"""

from __future__ import annotations

import logging
from typing import Dict, Type, Union, Callable

from .base import BasePCell

logger = logging.getLogger(__name__)

# 延迟导入，避免循环依赖
_REGISTRY: Dict[str, Type[BasePCell]] = {}


def register(name: str, pcell_cls: Type[BasePCell] = None) -> Union[Callable, None]:
    """注册PCell类，支持装饰器用法。

    用法:
        @register("CAP_MIM")
        class MIMCapacitor(BasePCell): ...

        # 或直接调用
        register("CAP_MIM", MIMCapacitor)
    """
    if pcell_cls is not None:
        # 直接调用: register("CAP_MIM", cls)
        _REGISTRY[name] = pcell_cls
        return None

    # 装饰器用法: @register("CAP_MIM")
    def decorator(cls: Type[BasePCell]) -> Type[BasePCell]:
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_pcell(cell_type: str) -> BasePCell:
    """按类型名获取PCell实例。

    Args:
        cell_type: PCell类型名，如 "CAP_MIM"

    Returns:
        BasePCell实例

    Raises:
        ValueError: 未知类型
    """
    # 确保已自动注册
    _auto_register()

    cls = _REGISTRY.get(cell_type)
    if cls is None:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(f"未知PCell类型: {cell_type} (可用: {available})")
    return cls()


def list_pcells() -> Dict[str, Type[BasePCell]]:
    """列出所有已注册的PCell。"""
    _auto_register()
    return dict(_REGISTRY)


def _auto_register() -> None:
    """触发子模块导入，确保PCell类已注册。"""
    if _REGISTRY:
        return  # 已注册过

    # 导入各PCell模块，触发@register装饰器
    try:
        from .mim_capacitor.pcell import MIMCapacitor  # noqa: F401
    except ImportError as e:
        logger.warning(f"PCell导入失败: MIMCapacitor: {e}")
    try:
        from .spiral_inductor.pcell import SpiralInductor  # noqa: F401
    except ImportError as e:
        logger.warning(f"PCell导入失败: SpiralInductor: {e}")
    try:
        from .transmission_line.pcell import TransmissionLine  # noqa: F401
    except ImportError as e:
        logger.warning(f"PCell导入失败: TransmissionLine: {e}")
