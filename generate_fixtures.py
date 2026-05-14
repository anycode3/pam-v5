"""生成L-match 3器件集成测试夹具。

布局:
       (0,600)              (800,600)
          ┌────── TL1 ──────┐
          │  w=20, l=400    │
       (0,400)          (800,400)
          │                │
          │                L1 (spiral)
          │                ir=35, t=2.0, w=10
          │                │
       (0,0)           (800,-400)
          │
       C1 (MIM cap)
       40x40um
          │
       (0,-200)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))
pcell_dir = Path(__file__).parent
sys.path.insert(0, str(pcell_dir))

import klayout.db as db
from pcells.registry import get_pcell

FIXTURES = Path("tests/fixtures/l_match")


def generate_initial_gds():
    """生成初始版图GDS: C1=2pF + TL1=50Ω/400um + L1=1nH"""
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("L_MATCH_3DEV")

    # C1: 2pF (40x40um), 位于(0, -200)附近
    cap_pcell = get_pcell("CAP_MIM")
    c1 = layout.create_cell("C1_CAP_MIM")
    cap_pcell.generate(c1, {"length": 40, "width": 40})
    # C1放在(0, -200)附近，即中心偏移
    top.insert(db.CellInstArray(c1.cell_index(), db.Trans(db.Point(0, -200000))))

    # TL1: 50Ω/400um, 位于y=400~600区间
    tl_pcell = get_pcell("TL_MICROSTRIP")
    tl1 = layout.create_cell("TL1_TL_MICROSTRIP")
    tl_pcell.generate(tl1, {"width": 20, "length": 400, "angle": 0.0})
    # TL1 P1在(0,500), P2在(400,500)
    top.insert(db.CellInstArray(tl1.cell_index(), db.Trans(db.Point(0, 400000))))

    # L1: 1nH (ir=35, t=2.0, w=10, s=8), 位于(800, 0)附近
    ind_pcell = get_pcell("IND_SPIRAL")
    l1 = layout.create_cell("L1_IND_SPIRAL")
    ind_pcell.generate(l1, {"inner_radius": 35, "turns": 2.0, "width": 10, "spacing": 8, "angle": 0.0})
    # L1中心在(800,0), PI在(800, 53+10=63um above center), NIN在(800-35, -63)
    # 实际需要L1的PI和TL1的P2对齐
    # TL1 P2在x=400um, L1 PI在x=0(本地), 所以L1实例偏移到x=800000
    top.insert(db.CellInstArray(l1.cell_index(), db.Trans(db.Point(800000, 0))))

    gds_path = FIXTURES / "initial_layout.gds"
    layout.write(str(gds_path))
    print(f"初始版图: {gds_path}")
    return gds_path


def generate_netlist():
    """生成3器件KiCad网表。"""
    netlist = """(export (version "E")
  (design
    (source "/pam/l_match_3dev/l_match.kicad_sch")
    (date "2026-05-14")
    (tool "KiCad 8.0")
  )
  (components
    (comp (ref "C1")
      (value "2pF")
      (footprint "RF:MIM_Cap")
      (libsource (lib "RF") (part "CAP_MIM") (description "MIM Capacitor"))
    )
    (comp (ref "TL1")
      (value "50Ohm/400um")
      (footprint "RF:Microstrip")
      (libsource (lib "RF") (part "TL_MICROSTRIP") (description "Microstrip Transmission Line"))
    )
    (comp (ref "L1")
      (value "1nH")
      (footprint "RF:Spiral_Ind")
      (libsource (lib "RF") (part "IND_SPIRAL") (description "Spiral Inductor"))
    )
  )
  (nets
    (net (code 1) (name "RFIN")
      (node (ref "TL1") (pin "P1"))
    )
    (net (code 2) (name "NET_TL1_L1")
      (node (ref "TL1") (pin "P2"))
      (node (ref "L1") (pin "PI"))
    )
    (net (code 3) (name "NET_C1_TL1")
      (node (ref "C1") (pin "PI"))
      (node (ref "TL1") (pin "P1"))
    )
    (net (code 4) (name "GND")
      (node (ref "C1") (pin "NIN"))
      (node (ref "L1") (pin "NIN"))
    )
  )
)
"""
    path = FIXTURES / "kicad_netlist.net"
    path.write_text(netlist, encoding="utf-8")
    print(f"网表: {path}")


def generate_target_params():
    """生成5个场景的目标参数JSON。"""

    # S1: 单器件微调 C1 2pF→3pF
    s1 = [
        {"reference": "C1", "type": "capacitor_mim", "params": {"capacitance_pf": 3.0}},
    ]

    # S2: 相邻器件联动 TL1 λ/4→λ/2 + L1 1nH→2nH
    s2 = [
        {"reference": "TL1", "type": "TL_MICROSTRIP", "params": {"impedance_ohm": 50.0, "length_um": 2000}},
        {"reference": "L1", "type": "inductor_spiral", "params": {"inductance_nH": 2.0}},
    ]

    # S3: 大跳变 L1 1nH→5nH (面积翻3倍)
    s3 = [
        {"reference": "L1", "type": "inductor_spiral", "params": {"inductance_nH": 5.0}},
    ]

    # S4: DRC交叉冲突 C1 2pF→8pF(无此值用5pF) + L1 1nH→4nH
    s4 = [
        {"reference": "C1", "type": "capacitor_mim", "params": {"capacitance_pf": 5.0}},
        {"reference": "L1", "type": "inductor_spiral", "params": {"inductance_nH": 4.0}},
    ]

    # S5: 极端参数 L1 1nH→10nH (超出查表范围或极大面积)
    # 10nH不在查表中, mapper应报错或映射到最大值
    s5 = [
        {"reference": "L1", "type": "inductor_spiral", "params": {"inductance_nH": 10.0}},
    ]

    for name, data in [("s1", s1), ("s2", s2), ("s3", s3), ("s4", s4), ("s5", s5)]:
        path = FIXTURES / f"target_{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"目标参数: {path}")


def main():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    generate_initial_gds()
    generate_netlist()
    generate_target_params()
    print("\n夹具生成完成！")


if __name__ == "__main__":
    main()
