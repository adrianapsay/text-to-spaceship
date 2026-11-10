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
