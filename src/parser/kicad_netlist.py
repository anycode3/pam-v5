"""KiCad 网表解析器（S-expression 格式）。

继承自 NetlistParser，解析 KiCad 导出的网表文件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import sexpdata

from .base import NetlistParser
from .factory import register_parser
from .types import Component, Net


@register_parser("kicad")
class KiCadNetlistParser(NetlistParser):
    """解析 KiCad S-expression 格式网表。"""

    @staticmethod
    def format_name() -> str:
        return "kicad"

    def parse(self, path: str | Path) -> tuple[list[Component], list[Net]]:
        """解析 KiCad 网表文件。"""
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        data = sexpdata.loads(content)

        components = self._parse_components(data)
        nets = self._parse_nets(data)

        return components, nets

    def _find_section(self, data: list, key: str) -> list[list]:
        """在S-expression中查找所有指定key的子段。"""
        results = []
        if not isinstance(data, list):
            return results
        for item in data:
            if isinstance(item, list) and len(item) > 0:
                first = item[0]
                if isinstance(first, sexpdata.Symbol) and first.value() == key:
                    results.append(item)
        return results

    def _find_value(self, section: list, key: str) -> Optional[str]:
        """在子段中查找key对应的值（直接子级）。"""
        for item in section:
            if isinstance(item, list) and len(item) >= 2:
                first = item[0]
                if isinstance(first, sexpdata.Symbol) and first.value() == key:
                    v = item[1]
                    if isinstance(v, sexpdata.Symbol):
                        return v.value()
                    return str(v)
        return None

    def _parse_components(self, data: list) -> list[Component]:
        """解析 components 段。"""
        components = []
        comp_sections = self._find_section(data, "components")
        if not comp_sections:
            return components

        for comp in self._find_section(comp_sections[0], "comp"):
            ref = self._find_value(comp, "ref") or ""
            value = self._find_value(comp, "value") or ""

            lib = ""
            name = ""
            footprint = ""
            for item in comp:
                if isinstance(item, list) and len(item) > 0:
                    first = item[0]
                    if isinstance(first, sexpdata.Symbol):
                        val = first.value()
                        if val == "libsource":
                            lib = self._find_value(item, "lib") or ""
                            name = self._find_value(item, "part") or ""
                        elif val == "footprint":
                            footprint = self._find_value(item, "footprint") or ""

            ext = {}
            if footprint:
                ext["footprint"] = footprint

            components.append(Component(
                reference=ref, value=value, lib=lib, name=name, ext=ext,
            ))

        return components

    def _parse_nets(self, data: list) -> list[Net]:
        """解析 nets 段。"""
        nets = []
        net_sections = self._find_section(data, "nets")
        if not net_sections:
            return nets

        for net in self._find_section(net_sections[0], "net"):
            name = self._find_value(net, "name") or ""
            nodes = []
            for node in self._find_section(net, "node"):
                ref = self._find_value(node, "ref") or ""
                pin = self._find_value(node, "pin") or ""
                if ref and pin:
                    nodes.append((ref, pin))
            nets.append(Net(name=name, nodes=nodes))

        return nets
