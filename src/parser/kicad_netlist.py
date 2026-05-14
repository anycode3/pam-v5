"""KiCad网表解析器，基于sexpdata库。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import sexpdata


@dataclass
class Pin:
    """器件引脚信息。"""
    number: str           # 引脚编号/名称，如 "1", "PI", "P1"
    name: str             # 引脚功能名
    net: Optional[str] = None  # 所属网络名，未连接为None


@dataclass
class Component:
    """网表中的器件。"""
    reference: str  # 如 C1, L1, Q1
    value: str      # 如 2pF, 2nH
    lib: str        # 器件库来源
    name: str       # 器件符号名
    pins: list[Pin] = field(default_factory=list)


@dataclass
class Net:
    """网络连接信息。"""
    name: str
    nodes: list[tuple[str, str]] = field(default_factory=list)  # [(ref, pin_name), ...]


class KiCadNetlistParser:
    """解析KiCad S-expression格式网表。"""

    def parse(self, path: str | Path) -> tuple[list[Component], list[Net]]:
        """解析网表文件，返回器件列表和网络列表。"""
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        data = sexpdata.loads(content)

        components = self._parse_components(data)
        nets = self._parse_nets(data)

        # 从nets回填器件引脚信息（KiCad网表中pin信息在net段而非comp段）
        self._fill_pins_from_nets(components, nets)

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
                    # 值可能是Symbol或字面量
                    if isinstance(v, sexpdata.Symbol):
                        return v.value()
                    return str(v)
        return None

    def _parse_components(self, data: list) -> list[Component]:
        """解析components段。"""
        components = []
        comp_sections = self._find_section(data, "components")
        if not comp_sections:
            return components

        for comp in self._find_section(comp_sections[0], "comp"):
            ref = self._find_value(comp, "ref") or ""
            value = self._find_value(comp, "value") or ""

            # libsource嵌套: (libsource (lib "RF") (part "CAP_MIM"))
            lib = ""
            name = ""
            for item in comp:
                if isinstance(item, list) and len(item) > 0:
                    first = item[0]
                    if isinstance(first, sexpdata.Symbol) and first.value() == "libsource":
                        lib = self._find_value(item, "lib") or ""
                        name = self._find_value(item, "part") or ""

            components.append(Component(
                reference=ref, value=value, lib=lib, name=name,
            ))

        return components

    def _parse_nets(self, data: list) -> list[Net]:
        """解析nets段。"""
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

    def _fill_pins_from_nets(self, components: list[Component], nets: list[Net]) -> None:
        """从net段回填器件引脚信息。

        KiCad网表中comp段通常不含pins子段，pin连接信息在net的node中。
        """
        ref_to_comp: dict[str, Component] = {c.reference: c for c in components}
        existing_pins: dict[str, set[str]] = {c.reference: {p.number for p in c.pins} for c in components}

        for net in nets:
            for ref, pin_name in net.nodes:
                comp = ref_to_comp.get(ref)
                if comp and pin_name not in existing_pins[ref]:
                    comp.pins.append(Pin(number=pin_name, name=pin_name, net=net.name))
                    existing_pins[ref].add(pin_name)
                elif comp:
                    # pin已存在，只更新net
                    for pin in comp.pins:
                        if pin.number == pin_name:
                            pin.net = net.name
                            break

    def get_component_by_ref(
        self, components: list[Component], reference: str
    ) -> Optional[Component]:
        """按reference查找器件。"""
        for c in components:
            if c.reference == reference:
                return c
        return None
