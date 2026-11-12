"""Miniature deep groove ball bearings (SKF, shielded 2Z), read 2026-11-11 from the SKF product table for bore 3 to 6 mm (catalogue page copy).
Dimensions d (bore), D (outside diameter), B (width) and mass are the table's values."""
from parts_data._common import part, source, cost

PARTS = []
SKF_TABLE = "https://baoanjsc.com.vn/TaiLieu/single-row-deep-groove-ball-bearings-d3-6mm-skf-type-6-CATALOG-12068.pdf"

for designation, bore, outside, width, mass_kg in (
        ("623-2Z", 3, 10, 4, 0.0015), ("628/4-2Z", 4, 9, 3.5, 0.001), ("638/4-2Z", 4, 9, 4, 0.0013), ("619/4-2Z", 4, 11, 4, 0.0017), ("604-2Z", 4, 12, 4, 0.0021),
        ("624-2Z", 4, 13, 5, 0.0031), ("634-2Z", 4, 16, 5, 0.0054), ("628/5-2Z", 5, 11, 4, 0.0014), ("638/5-2Z", 5, 11, 5, 0.0016), ("619/5-2Z", 5, 13, 4, 0.0025),
        ("625-2Z", 5, 16, 5, 0.005), ("635-2Z", 5, 19, 6, 0.0093), ("628/6-2Z", 6, 13, 5, 0.0026), ("619/6-2Z", 6, 15, 5, 0.0039), ("626-2Z", 6, 19, 6, 0.0088)):
    part_id = "skf_bearing_" + designation.lower().replace("/", "_").replace("-", "_")
    PARTS.append(part(part_id, "SKF " + designation + " deep groove ball bearing, shielded (" + str(bore) + " x " + str(outside) + " x " + str(width) + " mm)", "mechanisms", "bearing", "SKF", designation,
        (outside, outside, width), round(mass_kg * 1000, 2), {"kind": "tube", "outer_diameter": outside, "inner_diameter": bore, "length": width},
        source("datasheet", SKF_TABLE, "SKF single row deep groove ball bearings, d 3 to 6 mm (product table)", ["dimensions_mm", "mass_g"],
               notes="d = " + str(bore) + " mm, D = " + str(outside) + " mm, B = " + str(width) + " mm, mass " + str(mass_kg) + " kg, from the SKF table row " + designation + ". Steel rings and balls, 2Z = metal shield on both sides.", date="2026-11-11"),
        vendor_country="Sweden", distributors=["SKF distributors", "RS Components", "Misumi"], status="in_production", fidelity="envelope", material="bearing steel, steel shields",
        mechanism={"type": "deep groove ball bearing", "bore_mm": bore, "outside_diameter_mm": outside, "width_mm": width}, cost=cost(basis="distributor")))
