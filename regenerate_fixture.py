"""Regenerate initial_layout.gds fixture with PIN_MARKER_LAYER.

布局：C1(0,100) → TL1(300,100) → L1(600,100)，水平排列不相连。
初始状态各器件金属不连通。
"""

import sys
sys.path.insert(0, 'src')
sys.path.insert(0, '.')

import klayout.db as db
from pcells.registry import get_pcell

layout = db.Layout()
layout.dbu = 0.001
top = layout.create_cell("L_MATCH")

# C1 (1pF: length=40, width=40) - y=100um
pcell = get_pcell("CAP_MIM")
c1 = layout.create_cell("C1_CAP_MIM")
pcell.generate(c1, {"length": 40, "width": 40})
top.insert(db.CellInstArray(c1.cell_index(), db.Trans(db.Point(0, 100000))))

# TL1 (50Ω/500um) - y=100um
tl_pcell = get_pcell("TL_MICROSTRIP")
tl1 = layout.create_cell("TL1_TL_MICROSTRIP")
tl_pcell.generate(tl1, {"width": 20, "length": 500, "angle": 0.0})
top.insert(db.CellInstArray(tl1.cell_index(), db.Trans(db.Point(300000, 100000))))

# L1 (inductor: ir=35, turns=2.0, width=10, spacing=8) - y=100um
ind_pcell = get_pcell("IND_SPIRAL")
l1 = layout.create_cell("L1_IND_SPIRAL")
ind_pcell.generate(l1, {"inner_radius": 35, "turns": 2.0, "width": 10, "spacing": 8, "angle": 0.0})
top.insert(db.CellInstArray(l1.cell_index(), db.Trans(db.Point(600000, 100000))))

layout.write("tests/fixtures/l_match/initial_layout.gds")

# Verify
layout2 = db.Layout()
layout2.read("tests/fixtures/l_match/initial_layout.gds")
marker_layer = layout2.layer(db.LayerInfo(255, 0))
total = sum(1 for c in layout2.each_cell() for _ in c.shapes(marker_layer).each())
print(f"Total PIN markers: {total}")
print("Fixture regenerated successfully")
