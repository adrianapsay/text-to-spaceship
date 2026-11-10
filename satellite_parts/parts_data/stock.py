"""Stock material: bars, plates, shafts, extrusions. Standard metric sizes, DERIVED (no vendor); masses from density."""
from parts_data._common import part, source, cost
PARTS = []
AL = 2.70
for id, x, y, length in (("10x10", 10, 10, 100), ("10x10_long", 10, 10, 300), ("20x10", 20, 10, 100), ("20x20", 20, 20, 100), ("25x25", 25, 25, 100), ("8p5x8p5_rail", 8.5, 8.5, 113.5)):
    PARTS.append(part("al_bar_" + id, "Aluminium 6061 rectangular bar " + str(x) + " x " + str(y) + " x " + str(length) + " mm", "stock", "bar", "generic", "6061-T6 bar", (length, x, y), round(x * y * length * AL / 1000, 1), {"kind": "box", "x": length, "y": x, "z": y},
        source("derived", "https://www.mcmaster.com", "standard metric bar stock sizes (no datasheet needed; mass from 2.70 g/cm3)", ["dimensions_mm"], notes="Generic stock; the 8.5 x 8.5 x 113.5 mm bar is a 1U rail blank per CDS rail width."), status="in_production", material="aluminium 6061-T6", mass_note="derived", cost=cost(basis="unknown")))
for id, dims in (("1u_1p5", (98, 98, 1.5)), ("1u_3", (98, 98, 3.0)), ("3u_side_2", (325, 83, 2.0)), ("pc104_1p6", (95.9, 90.2, 1.6))):
    PARTS.append(part("al_plate_" + id, "Aluminium 6061 plate " + " x ".join(str(v) for v in dims) + " mm", "stock", "plate", "generic", "6061-T6 plate", dims, round(dims[0] * dims[1] * dims[2] * AL / 1000, 1), {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]},
        source("derived", "https://www.mcmaster.com", "standard plate sizes cut to CubeSat faces", ["dimensions_mm"]), status="in_production", material="aluminium 6061-T6", mass_note="derived", cost=cost(basis="unknown")))
for id, diameter, length in (("3x50", 3, 50), ("4x80", 4, 80), ("6x100", 6, 100), ("8x100", 8, 100)):
    PARTS.append(part("ss_shaft_" + id, "Stainless steel shaft " + str(diameter) + " mm x " + str(length) + " mm (h6)", "stock", "shaft", "generic", "303 stainless shaft", (length, diameter, diameter), round(3.14159 * (diameter / 2) ** 2 * length * 7.9 / 1000, 1), {"kind": "cylinder", "diameter": diameter, "length": length, "axis": "x"},
        source("derived", "https://www.mcmaster.com", "standard ground shaft sizes", ["dimensions_mm"]), status="in_production", material="stainless steel 303", mass_note="derived", cost=cost(basis="unknown")))
for length in (100, 200, 300):
    PARTS.append(part("extrusion_2020_" + str(length), "20 x 20 mm T-slot aluminium extrusion, " + str(length) + " mm", "stock", "extrusion", "generic", "2020 T-slot", (20, 20, length), round(length * 0.42, 1), {"kind": "extrusion_2020", "length": length},
        source("derived", "https://www.mcmaster.com", "2020 T-slot profile (about 0.42 kg/m typical)", ["dimensions_mm"], notes="Simplified profile (four slots, no center bore)."), status="in_production", material="aluminium 6063-T5", mass_note="derived", cost=cost(basis="unknown")))
for id, x, y, z, t in (("20x20x20", 20, 20, 20, 2), ("30x30x20", 30, 20, 30, 2), ("40x40x25", 40, 25, 40, 3)):
    PARTS.append(part("al_bracket_l_" + id, "Aluminium L-bracket " + id + " mm, " + str(t) + " mm wall", "stock", "bracket", "generic", "L-bracket", (x, y, z), round((x * y + z * y) * t * AL / 1000, 1), {"kind": "l_bracket", "x": x, "y": y, "z": z, "thickness": t},
        source("derived", "https://www.mcmaster.com", "generic angle bracket", ["dimensions_mm"]), status="in_production", material="aluminium 6061", mass_note="derived", cost=cost(basis="unknown")))
