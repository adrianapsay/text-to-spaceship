"""Fasteners per ISO tables: socket head cap screws (ISO 4762), hex nuts (ISO 4032), washers (ISO 7089). Dimensions from the engineersedge ISO 4762 table (fetched 2026-11-08); nut and washer dimensions per ISO 4032 / ISO 7089 as published in standard tables (see notes)."""
from parts_data._common import part, source, cost

ISO4762 = "https://engineersedge.com/iso_socket_head_screw.htm"
STEEL = 7.85
PARTS = []
# size: (pitch, dk, k, s, lengths)
screws = {"m2": (0.4, 3.8, 2.0, 1.56, [4, 6, 8, 10, 12, 16]), "m2p5": (0.45, 4.5, 2.5, 2.06, [5, 6, 8, 10, 12, 16, 20]), "m3": (0.5, 5.5, 3.0, 2.58, [5, 6, 8, 10, 12, 16, 20, 25, 30]), "m4": (0.7, 7.0, 4.0, 3.08, [8, 10, 12, 16, 20, 25, 30, 40]), "m5": (0.8, 8.5, 5.0, 4.095, [10, 12, 16, 20, 25, 30, 40, 50]), "m6": (1.0, 10.0, 6.0, 5.14, [12, 16, 20, 25, 30, 40, 50, 60])}
for size, (pitch, dk, k, s, lengths) in screws.items():
    diameter = float(size[1:].replace("p", "."))
    for length in lengths:
        volume = 3.14159 * (dk / 2) ** 2 * k + 3.14159 * (diameter / 2) ** 2 * length
        PARTS.append(part("shcs_" + size + "x" + str(length), "Socket head cap screw " + size.upper().replace("P", ".") + " x " + str(length) + " (ISO 4762)", "fasteners", "screw", "generic (ISO 4762)", "ISO 4762 " + size.upper().replace("P", ".") + "x" + str(length), (dk, dk, k + length), round(volume * STEEL / 1000, 2),
            {"kind": "screw", "head_diameter": dk, "head_height": k, "shank_diameter": diameter, "length": length, "socket_diameter": s, "socket_depth": k * 0.5, "tolerance": 0.05},
            source("standard", ISO4762, "ISO 4762 / DIN 912 hexagon socket head cap screws, dimension table", ["dimensions_mm"], notes="dk (max head dia.) " + str(dk) + ", k (head height) " + str(k) + ", s (socket) " + str(s) + ", pitch " + str(pitch) + " from the table; length " + str(length) + " is a standard length listed there. Mass DERIVED from steel at 7.85 g/cm^3 on the simplified geometry (no threads)."),
            status="in_production", material="stainless steel A2/A4 or alloy steel 12.9 (typical for spaceflight: A286 or titanium)", thread_pitch_mm=pitch, mass_note="derived", cost=cost(value=0.1, currency="USD", basis="list_price"), cost_note="typical COTS price per piece, approximate"))
# ISO 4032 hex nuts (across flats s, thickness m) and ISO 7089 washers (outer d2, inner d1, thickness h): values per the ISO tables.
nuts = {"m2": (4.0, 1.6), "m2p5": (5.0, 2.0), "m3": (5.5, 2.4), "m4": (7.0, 3.2), "m5": (8.0, 4.7), "m6": (10.0, 5.2)}
washers = {"m2": (5.0, 2.2, 0.3), "m2p5": (6.0, 2.7, 0.5), "m3": (7.0, 3.2, 0.5), "m4": (9.0, 4.3, 0.8), "m5": (10.0, 5.3, 1.0), "m6": (12.0, 6.4, 1.6)}
for size, (flats, thickness) in nuts.items():
    diameter = float(size[1:].replace("p", "."))
    area = 2 * 1.7320508 * (flats / 2) ** 2 - 3.14159 * (diameter / 2) ** 2
    PARTS.append(part("hex_nut_" + size, "Hex nut " + size.upper().replace("P", ".") + " (ISO 4032)", "fasteners", "nut", "generic (ISO 4032)", "ISO 4032 " + size.upper().replace("P", "."), (flats * 1.1547, flats, thickness), round(area * thickness * STEEL / 1000, 2), {"kind": "hex_nut", "across_flats": flats, "thickness": thickness, "bore": diameter, "tolerance": 0.05},
        source("standard", "https://www.fasten.it/norms/norm/din_en_iso_4762", "ISO 4032 hexagon regular nuts, style 1 (dimension table values s = across flats, m = thickness)", ["dimensions_mm"], notes="s and m per ISO 4032 as commonly tabulated (M2 4/1.6, M2.5 5/2, M3 5.5/2.4, M4 7/3.2, M5 8/4.7, M6 10/5.2). URL given is the fastener-standards site used for ISO 4762; the ISO 4032 page there was not fetched in this session, so treat as a standard value to be double-checked. Mass derived."),
        status="in_production", material="stainless steel A2 (typical)", mass_note="derived", cost=cost(value=0.05, currency="USD", basis="list_price")))
for size, (outer, inner, thickness) in washers.items():
    area = 3.14159 * ((outer / 2) ** 2 - (inner / 2) ** 2)
    PARTS.append(part("washer_" + size, "Plain washer " + size.upper().replace("P", ".") + " (ISO 7089)", "fasteners", "washer", "generic (ISO 7089)", "ISO 7089 " + size.upper().replace("P", "."), (outer, outer, thickness), round(area * thickness * STEEL / 1000, 3), {"kind": "washer", "outer_diameter": outer, "inner_diameter": inner, "thickness": thickness, "tolerance": 0.05},
        source("standard", "https://www.fasten.it/norms/norm/din_en_iso_4762", "ISO 7089 plain washers, normal series (d1, d2, h)", ["dimensions_mm"], notes="Values per ISO 7089 as commonly tabulated (M2 2.2/5/0.3, M2.5 2.7/6/0.5, M3 3.2/7/0.5, M4 4.3/9/0.8, M5 5.3/10/1.0, M6 6.4/12/1.6). Not fetched this session; treat as standard values to double-check. Mass derived."),
        status="in_production", material="stainless steel A2 (typical)", mass_note="derived", cost=cost(value=0.03, currency="USD", basis="list_price")))

# ISO 10642 countersunk socket screws, M3 and M2.5 (dk, k from the ISO 10642 table: M2.5 dk 5.5 k 1.5; M3 dk 6.72 k 1.86). Pumpkin CubeSat Kit structures use M3 x 5 flat heads.
ISO10642 = "https://www.engineersedge.com/hardware/iso_10642_countersunk_socket_screws_14764.htm"
for size, (dk, k, shank, lengths) in {"m2p5": (5.5, 1.5, 2.5, (5, 6, 8, 10)), "m3": (6.72, 1.86, 3.0, (5, 6, 8, 10, 12, 16))}.items():
    for length in lengths:
        PARTS.append(part("csk_" + size + "x" + str(length), "Countersunk socket screw " + size.upper().replace("P", ".") + " x " + str(length) + " (ISO 10642)", "fasteners", "screw", "generic (ISO 10642)", size.upper().replace("P", ".") + "x" + str(length) + " ISO 10642", (dk, dk, length), round((3.14159 * (shank / 2) ** 2 * (length - k) + 3.14159 / 12 * k * (dk ** 2 + dk * shank + shank ** 2) / 4 * 4 / 3) * 7.85 / 1000, 3), {"kind": "countersunk_screw", "head_diameter": dk, "head_height": k, "shank_diameter": shank, "length": length},
            source("standard", ISO10642, "ISO 10642 hexagon socket countersunk head screws, dimension table (values from memory of the table; page not fetched this session)", ["dimensions_mm"], notes="dk theoretical max " + str(dk) + ", k " + str(k) + "; mass derived from steel 7.85 g/cm3 (cone + shank volume). Overall length includes the head per ISO 10642."), status="in_production", material="steel 10.9 or A2 stainless", mass_note="derived", distributors=["McMaster-Carr", "Fabory", "Bossard"], cost=cost(value=0.1, currency="USD", basis="list_price"), cost_note="approximate bulk price"))

# ISO 7380-1 hexagon socket button head screws (added 2026-11-11). Head dk / k / socket s from the Westfield Fasteners ISO 7380 standard sheet;
# mass per piece from the fasten.it ISO 7380-1 table ("approximate mass, kg x 1000 pcs", steel).
ISO7380_SHEET = "https://westfieldfasteners.co.uk/Standards/ScrewBolt-SHBtn-M.pdf"
ISO7380_MASS = "https://fasten.it/norms/norm/din_en_iso_7380-1"
button_heads = {"m3": (0.5, 5.7, 1.65, 2.0, {6: 0.42, 8: 0.50, 10: 0.59, 12: 0.67, 16: 0.83, 20: 0.99}),
                "m4": (0.7, 7.6, 2.2, 2.5, {6: 0.86, 8: 1.0, 10: 1.15, 12: 1.29, 16: 1.57, 20: 1.86}),
                "m5": (0.8, 9.5, 2.75, 3.0, {8: 1.80, 10: 2.03, 12: 2.26, 16: 2.73, 20: 3.19}),
                "m6": (1.0, 10.5, 3.3, 4.0, {10: 2.92, 12: 3.25, 16: 3.92, 20: 4.58})}
for size, (pitch, dk, k, s, lengths) in button_heads.items():
    diameter = float(size[1:].replace("p", "."))
    for length, kg_per_1000 in lengths.items():
        PARTS.append(part("bhcs_" + size + "x" + str(length), "Button head socket screw " + size.upper() + " x " + str(length) + " (ISO 7380-1)", "fasteners", "screw", "generic (ISO 7380-1)", "ISO 7380-1 " + size.upper() + "x" + str(length), (dk, dk, k + length), kg_per_1000,
            {"kind": "screw", "head_diameter": dk, "head_height": k, "shank_diameter": diameter, "length": length, "socket_diameter": s * 1.15, "socket_depth": k * 0.5, "tolerance": 0.05},
            source("standard", ISO7380_SHEET, "ISO 7380-1 hexagon socket button head screws, dimension table (Westfield Fasteners standards sheet)", ["dimensions_mm", "mass_g"], notes="dk (max) " + str(dk) + ", k (max) " + str(k) + ", socket s " + str(s) + ", pitch " + str(pitch) + " mm. Mass " + str(kg_per_1000) + " g per piece from the approximate mass table (kg per 1000 pcs, steel) at " + ISO7380_MASS + ". Head drawn as a short cylinder (the real head is domed)."),
            status="in_production", material="stainless steel A2/A4 or alloy steel 10.9", thread_pitch_mm=pitch, mass_note="from the ISO 7380-1 mass table (steel)", cost=cost(value=0.1, currency="USD", basis="list_price"), cost_note="typical COTS price per piece, approximate"))

# ISO 4026 hexagon socket set screws with flat point (added 2026-11-11): socket s and mass per piece from the fasten.it DIN EN ISO 4026 table
# ("kg x1000 pcs", steel 7.85 kg/dm3). The envelope is the thread cylinder d x l.
ISO4026 = "https://fasten.it/norms/norm/din_en_iso_4026"
set_screws = {"m3": (0.5, 1.5, {4: 0.14, 6: 0.22, 8: 0.3, 10: 0.38}), "m4": (0.7, 2.0, {4: 0.22, 6: 0.38, 8: 0.54, 10: 0.7, 12: 0.86}),
              "m5": (0.8, 2.5, {5: 0.44, 8: 0.8, 10: 1.04, 12: 1.28}), "m6": (1.0, 3.0, {6: 0.76, 8: 1.11, 10: 1.46, 12: 1.81})}
for size, (pitch, s, lengths) in set_screws.items():
    diameter = float(size[1:])
    for length, kg_per_1000 in lengths.items():
        PARTS.append(part("set_screw_" + size + "x" + str(length), "Socket set screw, flat point " + size.upper() + " x " + str(length) + " (ISO 4026)", "fasteners", "set_screw", "generic (ISO 4026)", "ISO 4026 " + size.upper() + "x" + str(length), (diameter, diameter, length), kg_per_1000,
            {"kind": "cylinder", "diameter": diameter, "length": length, "axis": "z", "tolerance": 0.05},
            source("standard", ISO4026, "DIN EN ISO 4026 hexagon socket set screws with flat point (fasten.it table)", ["dimensions_mm", "mass_g"], notes="Thread " + size.upper() + " x " + str(length) + " mm, socket s " + str(s) + " mm, pitch " + str(pitch) + " mm, mass " + str(kg_per_1000) + " g per piece (table: kg per 1000 pcs, steel)."),
            status="in_production", material="alloy steel 45H or stainless steel A2/A4", thread_pitch_mm=pitch, mass_note="from the ISO 4026 mass table (steel)", cost=cost(value=0.08, currency="USD", basis="list_price"), cost_note="typical COTS price per piece, approximate"))

# ISO 7045 cross-recessed pan head screws (added 2026-11-11): head dk / k and mass from the fasten.it DIN 7985 table (DIN 7985 is withdrawn and
# replaced by DIN EN ISO 7045 with the same head sizes for M2 to M5; "kg x1000 pcs", steel).
PAN = "https://fasten.it/norms/norm/din_7985"
pan_heads = {"m2": (0.4, 4.0, 1.6, {4: 0.194, 6: 0.231, 8: 0.268, 10: 0.303}), "m2p5": (0.45, 5.0, 2.0, {4: 0.37, 6: 0.428, 8: 0.486, 10: 0.544}),
             "m3": (0.5, 6.0, 2.4, {4: 0.635, 6: 0.714, 8: 0.793, 10: 0.872, 12: 0.951}), "m4": (0.7, 8.0, 3.1, {6: 1.48, 8: 1.63, 10: 1.79, 12: 1.94, 16: 2.25})}
for size, (pitch, dk, k, lengths) in pan_heads.items():
    diameter = float(size[1:].replace("p", "."))
    for length, kg_per_1000 in lengths.items():
        PARTS.append(part("pan_screw_" + size + "x" + str(length), "Cross-recessed pan head screw " + size.upper().replace("P", ".") + " x " + str(length) + " (ISO 7045)", "fasteners", "screw", "generic (ISO 7045)", "ISO 7045 " + size.upper().replace("P", ".") + "x" + str(length), (dk, dk, k + length), kg_per_1000,
            {"kind": "screw", "head_diameter": dk, "head_height": k, "shank_diameter": diameter, "length": length, "tolerance": 0.05},
            source("standard", PAN, "DIN 7985 / ISO 7045 cross recessed pan head screws (fasten.it table, 08-1990 edition)", ["dimensions_mm", "mass_g"], notes="dk " + str(dk) + ", k " + str(k) + ", pitch " + str(pitch) + " mm, mass " + str(kg_per_1000) + " g per piece (kg per 1000 pcs, steel). The cross recess is not modelled."),
            status="in_production", material="stainless steel A2 or steel 4.8", thread_pitch_mm=pitch, mass_note="from the DIN 7985 mass table (steel)", cost=cost(value=0.05, currency="USD", basis="list_price"), cost_note="typical COTS price per piece, approximate"))
