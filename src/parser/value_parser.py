"""器件值字符串解析器。

将 KiCad 网表中的 value 字符串解析为电气参数字典，
供 MappingEngine 查表映射为几何参数。

支持的格式：
    CAP_MIM:      "1pF", "2.5pF", "10pF"
    IND_SPIRAL:   "1nH", "2.5nH", "5nH"
    TL_MICROSTRIP: "50Ohm/1000um", "50Ohm_2000um"
"""

import re
from typing import Dict


def parse_value(part_name: str, value_str: str) -> Dict[str, float]:
    """解析器件值字符串为电气参数。

    Args:
        part_name: 器件类型名，如 "CAP_MIM", "IND_SPIRAL", "TL_MICROSTRIP"
        value_str: 值字符串，如 "1pF", "2.5nH", "50Ohm/1000um"

    Returns:
        电气参数字典，如 {"capacitance_pf": 1.0}
    """
    parsers = {
        "CAP_MIM": _parse_capacitor,
        "IND_SPIRAL": _parse_inductor,
        "TL_MICROSTRIP": _parse_transmission_line,
    }
    parser = parsers.get(part_name)
    if parser is None:
        raise ValueError(f"不支持的器件类型: {part_name}")
    return parser(value_str)


def _parse_capacitor(value: str) -> Dict[str, float]:
    """解析电容值: "1pF", "2.5pF", "0.5pF" → {"capacitance_pf": float}"""
    m = re.match(r'^([\d.]+)\s*pF$', value, re.IGNORECASE)
    if m:
        return {"capacitance_pf": float(m.group(1))}
    # 尝试 fF
    m = re.match(r'^([\d.]+)\s*fF$', value, re.IGNORECASE)
    if m:
        return {"capacitance_pf": float(m.group(1)) / 1000.0}
    raise ValueError(f"无法解析电容值: '{value}'，期望格式如 '1pF'")


def _parse_inductor(value: str) -> Dict[str, float]:
    """解析电感值: "1nH", "2.5nH" → {"inductance_nH": float}"""
    m = re.match(r'^([\d.]+)\s*nH$', value, re.IGNORECASE)
    if m:
        return {"inductance_nH": float(m.group(1))}
    raise ValueError(f"无法解析电感值: '{value}'，期望格式如 '1nH'")


def _parse_transmission_line(value: str) -> Dict[str, float]:
    """解析传输线值: "50Ohm/1000um", "50Ohm_2000um" → {"impedance_ohm": float, "length_um": float}"""
    m = re.match(r'^([\d.]+)\s*Ohm\s*[/_]\s*([\d.]+)\s*um$', value, re.IGNORECASE)
    if m:
        return {"impedance_ohm": float(m.group(1)), "length_um": float(m.group(2))}
    raise ValueError(f"无法解析传输线值: '{value}'，期望格式如 '50Ohm/1000um'")


def value_to_device_type(part_name: str) -> str:
    """将网表中的 part name 映射为 mapping_rules.yaml 中的 device_type key。

    Args:
        part_name: 如 "CAP_MIM", "IND_SPIRAL", "TL_MICROSTRIP"

    Returns:
        device_type key，如 "capacitor_mim", "inductor_spiral", "transmission_line"
    """
    mapping = {
        "CAP_MIM": "capacitor_mim",
        "IND_SPIRAL": "inductor_spiral",
        "TL_MICROSTRIP": "transmission_line",
    }
    result = mapping.get(part_name)
    if result is None:
        raise ValueError(f"未知的器件类型: {part_name}")
    return result
