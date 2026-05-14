"""连线发现器：从版图+网表信息发现连线及其关联引脚。

策略：
1. 从网表获取连接关系（哪个pin连哪个pin）
2. 从PCell的get_pin_positions获取引脚坐标
3. 在两个引脚之间查找同层连通走线几何
4. 建立Connection对象

简化方案：对于两个相邻引脚，查找两者之间的直连走线段（水平/垂直矩形）。
"""

from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Tuple

import klayout.db as db

from .types import PinState, WireSegment, Connection
from src.pcells.registry import get_pcell

logger = logging.getLogger(__name__)


class WireFinder:
    """从版图+网表发现连线。"""

    def find_connections(
        self,
        layout: db.Layout,
        top_cell: db.Cell,
        netlist_nets: Dict[str, List[Tuple[str, str]]],
        ref_to_pcell: Dict[str, str],
        ref_to_params: Dict[str, dict],
    ) -> List[Connection]:
        """发现所有连线。

        Args:
            layout: KLayout Layout对象
            top_cell: 顶层Cell
            netlist_nets: {net_name: [(ref, pin_name), ...]} 从网表解析
            ref_to_pcell: {ref: pcell_name} 器件类型映射
            ref_to_params: {ref: params} 当前器件参数

        Returns:
            Connection列表
        """
        connections = []

        # 1. 计算所有引脚的全局位置
        pin_states = self._compute_all_pin_positions(
            layout, top_cell, netlist_nets, ref_to_pcell, ref_to_params
        )

        # 2. 对每个网络，建立引脚间的连线
        for net_name, pins in netlist_nets.items():
            if len(pins) < 2:
                continue

            # 获取该网络所有引脚的位置
            net_pin_states = []
            for ref, pin_name in pins:
                key = f"{ref}.{pin_name}"
                if key in pin_states:
                    net_pin_states.append(pin_states[key])

            # 对每对引脚，尝试发现连线
            for i in range(len(net_pin_states)):
                for j in range(i + 1, len(net_pin_states)):
                    pa = net_pin_states[i]
                    pb = net_pin_states[j]

                    # 查找两引脚之间的走线
                    wires = self._find_wires_between(
                        layout, top_cell, pa, pb
                    )

                    connections.append(Connection(
                        net_name=net_name,
                        pin_a=pa,
                        pin_b=pb,
                        wires=wires,
                    ))

        return connections

    def _compute_all_pin_positions(
        self,
        layout: db.Layout,
        top_cell: db.Cell,
        netlist_nets: Dict[str, List[Tuple[str, str]]],
        ref_to_pcell: Dict[str, str],
        ref_to_params: Dict[str, dict],
    ) -> Dict[str, PinState]:
        """计算所有引脚的全局位置。

        Returns:
            {"ref.pin_name": PinState}
        """
        pin_states: Dict[str, PinState] = {}

        # 收集所有需要的(ref, pin_name)
        needed: Dict[str, set] = {}  # {ref: {pin_name, ...}}
        for net_name, pins in netlist_nets.items():
            for ref, pin_name in pins:
                needed.setdefault(ref, set()).add(pin_name)

        # 对每个ref，获取PCell引脚位置并变换到全局坐标
        for ref, pin_names in needed.items():
            pcell_name = ref_to_pcell.get(ref)
            params = ref_to_params.get(ref, {})
            if not pcell_name or not params:
                continue

            try:
                pcell = get_pcell(pcell_name)
            except ValueError:
                continue

            local_pins = pcell.get_pin_positions(params)

            # 找到该ref对应的instance变换
            inst_trans = self._find_instance_transform(layout, top_cell, ref)
            if inst_trans is None:
                # 无变换，使用本地坐标
                for pin_name in pin_names:
                    if pin_name in local_pins:
                        pos = local_pins[pin_name]
                        pin_states[f"{ref}.{pin_name}"] = PinState(
                            name=pin_name, ref=ref, x=pos.x, y=pos.y
                        )
            else:
                # 应用instance变换
                dbu = layout.dbu
                for pin_name in pin_names:
                    if pin_name in local_pins:
                        pos = local_pins[pin_name]
                        # 本地坐标→全局坐标
                        local_pt = db.DPoint(pos.x, pos.y)
                        global_pt = inst_trans * local_pt
                        pin_states[f"{ref}.{pin_name}"] = PinState(
                            name=pin_name, ref=ref,
                            x=global_pt.x, y=global_pt.y
                        )

        return pin_states

    def _find_instance_transform(
        self, layout: db.Layout, top_cell: db.Cell, ref: str
    ) -> Optional[db.DCplxTrans]:
        """查找ref对应的instance变换矩阵。"""
        for inst in top_cell.each_inst():
            cell = inst.cell
            if cell.name.startswith(f"{ref}_") or cell.name == ref:
                # 获取instance的变换（含位移+旋转）
                trans = inst.dcplx_trans      # 返回DCplxTrans
                return trans
        return None

    def _find_wires_between(
        self,
        layout: db.Layout,
        top_cell: db.Cell,
        pin_a: PinState,
        pin_b: PinState,
    ) -> List[WireSegment]:
        """查找两个引脚之间的走线。

        当前简化实现：根据两引脚坐标生成直线/L型连线描述。
        实际走线从版图几何中识别（未来增强）。
        """
        ax, ay = pin_a.x, pin_a.y
        bx, by = pin_b.x, pin_b.y
        dx = abs(bx - ax)
        dy = abs(by - ay)

        # 判断连线类型
        if dx < 0.01 or dy < 0.01:
            # 直线（水平或垂直）
            return [WireSegment(
                layer=(6, 0),  # 默认Metal1层
                points=[(ax, ay), (bx, by)],
                width=10.0,    # 默认线宽
            )]
        else:
            # L型折线：先水平后垂直
            mid_x = bx if dx >= dy else ax
            mid_y = ay if dx >= dy else by
            return [WireSegment(
                layer=(6, 0),
                points=[(ax, ay), (mid_x, mid_y), (bx, by)],
                width=10.0,
            )]
