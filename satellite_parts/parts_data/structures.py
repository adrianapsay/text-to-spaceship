"""Structures and standards-based parts: CubeSat frames per CDS, vendor frames, PC/104 boards and stack hardware. Sources fetched 2026-11-08."""
from parts_data._common import part, source, cost

CDS = "https://www.nasa.gov/wp-content/uploads/2018/01/cubesatdesignspecificationrev14_12022-02-09.pdf"
CDS_DOC = "CubeSat Design Specification (CDS) Rev 14.1, Cal Poly, 2022-02-09"
SPECS = "https://cubesat-specs.readthedocs.io"
PC104 = "https://ereding.etsi.us.es/bibing/proyectos/use/abreproy/10654/fichero/DOCUMENTOS%252FPC104SPECV246.pdf"
ISIS_BROCHURE = "https://www.cubesatshop.com/wp-content/uploads/2016/06/ISIS-CubeSat-Structures-Brochure-v1.pdf"
ENDURO_CATALOGUE = "https://endurosat.com/wp-content/uploads/2022/02/Endurosat_Product_Catalogue_02_22.pdf"
PARTS = []

# Generic CDS-envelope skeleton frames (no vendor): envelope per CDS Rev 14.1 (1U-3U, 6U, 12U) and the cubesat-specs summary; mass derived from ISIS/EnduroSat primary-structure masses.
frames = [("1u", 1, 1, 1, 113.5, 100, 110, "CDS Rev 14.1"), ("1p5u", 1, 1, 1.5, 170.25, 100, 150, "CDS Rev 14.1"), ("2u", 1, 1, 2, 227.0, 100, 200, "CDS Rev 14.1"), ("3u", 1, 1, 3, 340.5, 100, 290, "CDS Rev 14.1"), ("6u", 2, 1, 3, 366.0, 100, 850, "CDS Rev 14.1 (226.3 x 100 x 366 mm)"), ("12u", 2, 2, 3, 366.0, 100, 1700, "CDS Rev 14.1 (226.3 x 226.3 x 366 mm)")]
for id, ux, uy, uz, length, _, mass, note in frames:
    width_x = 226.3 if ux == 2 else 100.0
    width_y = 226.3 if uy == 2 else 100.0
    PARTS.append(part("cds_frame_" + id, "Generic " + id.replace("p5", ".5").upper() + " CubeSat skeleton frame (CDS envelope)", "structures", "frame", "generic (per CDS Rev 14.1)", id.upper() + " skeleton", (width_x, width_y, length), mass,
        {"kind": "cubesat_frame", "units_x": 1, "units_y": 1, "units_z": uz, "length_z": length, "rail": 8.5, "wall": 1.5, "tolerance": 0.3} if ux == 1 and uy == 1 else {"kind": "box", "x": width_x, "y": width_y, "z": length},
        source("standard", CDS, CDS_DOC, ["dimensions_mm", "mounting"], notes="Envelope: " + note + "; 6U/12U widths 226.3 mm per cubesat-specs summary of CDS (" + SPECS + "). Rails 8.5 mm square (CDS 2.2.5 minimum). Mass is DERIVED: typical vendor primary-structure masses (ISIS 1U 100 g, EnduroSat 1U 120 g, 3U 243-290 g, 6U 850-900 g); 1.5U, 2U, 12U interpolated. 6U/12U drawn as envelope boxes only.", revision="14.1", date="2022-02-09"),
        vendor_country=None, distributors=[], status="in_production", material="aluminium 6061/6082 (typical; CDS requires 7075, 6061, 5005 or 5052 for rails)", fidelity="envelope_plus_features" if ux == 1 and uy == 1 else "envelope",
        mass_note="derived from vendor structures, see source.notes", max_satellite_mass_kg={"1u": 2.0, "1p5u": 3.0, "2u": 4.0, "3u": 6.0, "6u": 12.0, "12u": 24.0}[id], cost=cost(basis="unknown")))

# ISISPACE structures (brochure)
for id, model, dims, mass_primary, mass_total in (("1u", "1-Unit CubeSat structure", (100, 100, 113.5), 100, 200), ("2u", "2-Unit CubeSat structure", (100, 100, 227), 200, 390), ("3u", "3-Unit CubeSat structure", (100, 100, 340.5), 243, 304), ("6u", "6-Unit CubeSat structure", (226.3, 100, 340.5), 900, 1100)):
    units_z = {"1u": 1, "2u": 2, "3u": 3, "6u": 3}[id]
    PARTS.append(part("isis_structure_" + id, "ISISPACE " + model, "structures", "frame", "ISISPACE", model, dims, mass_primary,
        {"kind": "cubesat_frame", "units_z": units_z, "length_z": dims[2], "tolerance": 0.3} if id != "6u" else {"kind": "box", "x": 226.3, "y": 100, "z": 340.5},
        source("datasheet", ISIS_BROCHURE, "ISIS CubeSat Structures Brochure v1", ["dimensions_mm", "mass_g"], notes="Primary structure mass " + str(mass_primary) + " g; primary + secondary " + str(mass_total) + " g. Supports PC/104 and 94 x 94 mm PCBs. Material not stated in the brochure. ISIS lists the 6U envelope as 340.5 mm long (older 6U standard), not 366 mm."),
        vendor_country="Netherlands", distributors=["CubeSatShop", "direct"], status="in_production", fidelity="envelope_plus_features" if id != "6u" else "envelope", mass_with_secondary_g=mass_total, cost=cost(basis="quote")))

# EnduroSat structures (catalogue)
for id, model, dims, mass in (("1u", "1U CubeSat Structure", (100, 100, 113.5), 120), ("1p5u", "1.5U CubeSat Structure", (100, 100, 170.2), 152), ("3u", "3U CubeSat Structure", (100, 100, 340.5), 290), ("6u", "6U CubeSat Structure", (226.3, 100, 366), 850)):
    units_z = {"1u": 1, "1p5u": 1.5, "3u": 3, "6u": 3}[id]
    PARTS.append(part("endurosat_structure_" + id, "EnduroSat " + model, "structures", "frame", "EnduroSat", model, dims, mass,
        {"kind": "cubesat_frame", "units_z": units_z, "length_z": dims[2], "tolerance": 0.3} if id != "6u" else {"kind": "box", "x": 226.3, "y": 100, "z": 366},
        source("datasheet", ENDURO_CATALOGUE, "EnduroSat Product Catalogue 02/2022", ["dimensions_mm", "mass_g", "material"], date="2022-02"),
        vendor_country="Bulgaria", distributors=["direct"], status="legacy", status_note="2022 catalogue item; the 2026 endurosat.com structures list shows only 8U and 16U structures.", material="aluminium 6082", fidelity="envelope_plus_features" if id != "6u" else "envelope", cost=cost(basis="quote")))

# PC/104 standard board and stack hardware
PARTS.append(part("pc104_blank_board", "PC/104 blank module PCB (90.2 x 95.9 x 1.6 mm)", "structures", "pcb", "generic (PC/104 Consortium spec)", "PC/104 module outline", (95.9, 90.2, 1.6), 22, {"kind": "pc104_board", "x": 95.9, "y": 90.2, "z": 1.6},
    source("standard", PC104, "PC/104 Specification v2.4/2.6 (PC/104 Consortium)", ["dimensions_mm", "mounting"], notes="Module 3.550 x 3.775 in (90.2 x 95.9 mm); four mounting holes 0.125 in (3.2 mm); stack spacing 0.600 in (15.24 mm). Hole positions modelled 4.57 mm from the edges (common CubeSat Kit practice; the spec drawing coordinates were not extractable). Mass DERIVED from FR4 at 1.85 g/cm^3 for a 1.6 mm board (about 22 g)."),
    status="in_production", material="FR4 1.6 mm", mass_note="derived (FR4 volume)", cost=cost(basis="unknown")))
for height in (15.24, 23.5, 30.48):
    PARTS.append(part("pc104_standoff_m3_" + str(height).replace(".", "p"), "PC/104 stack standoff M3 hex, " + str(height) + " mm", "structures", "standoff", "generic", "M3 hex standoff " + str(height) + " mm", (5.5, 5.5, height), round(0.0279 * height * 1.1, 1), {"kind": "standoff", "across_flats": 5.5, "length": height, "bore": 2.5},
        source("standard", PC104, "PC/104 Specification (stack spacing 0.600 in)", ["dimensions_mm"], notes="15.24 mm = PC/104 stack pitch; 23.5 mm = GomSpace P31u/BP4 stack height (BP4 datasheet); 30.48 mm = two pitches. 5.5 mm across flats M3 female-female brass standoff is the common COTS size (DERIVED, not a spec value). Mass derived from brass volume."),
        status="in_production", material="brass or aluminium (COTS)", mass_note="derived", cost=cost(value=0.5, currency="USD", basis="list_price", source_url=None), cost_note="typical COTS price, approximate"))

# PocketQube (for completeness of the small-sat standards)
PARTS.append(part("pocketqube_1p_frame", "Generic 1p PocketQube envelope (50 mm cube)", "structures", "frame", "generic (PocketQube Standard Issue 1)", "1p", (50, 50, 50), 60, {"kind": "box", "x": 50, "y": 50, "z": 50},
    source("standard", SPECS, "PocketQube Standard Issue 1 (TU Delft / Alba Orbital / GAUSS, 2018) via cubesat-specs summary", ["dimensions_mm"], notes="Mass DERIVED (envelope only; max satellite mass 250 g)."), status="in_production", fidelity="envelope", mass_note="derived", cost=cost(basis="unknown")))

# Pumpkin CubeSat Kit structures: material (5052-H32 aluminium sheet, alodine) from the CubeSat Kit pages read earlier; masses and envelope follow the CDS and Pumpkin documentation from memory, marked unverified. CAD zips are public on cubesatkit.com.
for id, model, units, length, mass in (("1u", "CubeSat Kit 1U Skeletonized Chassis", 1, 113.5, 155), ("2u", "CubeSat Kit 2U Skeletonized Chassis", 2, 227.0, 240), ("3u", "CubeSat Kit 3U Skeletonized Chassis", 3, 340.5, 320)):
    PARTS.append(part("pumpkin_cubesatkit_" + id, "Pumpkin " + model, "structures", "frame", "Pumpkin Space Systems", model, (100, 100, length), mass, {"kind": "cubesat_frame", "units_z": units, "length_z": length, "tolerance": 0.3},
        source("unverified", "https://www.cubesatkit.com/content/design.html", "Pumpkin CubeSat Kit design page (material, CAD links)", ["material"], notes="Envelope per CDS Rev 14.1; chassis mass is FROM MEMORY of the CubeSat Kit datasheets (skeletonized chassis + cover plates) and must be checked. CAD: http://www.cubesatkit.com/files/CAD/"), vendor_country="USA", distributors=["direct (Pumpkin Space Systems)"], status="in_production", first_available_year=2003, material="aluminium 5052-H32 sheet, alodine 1200 finish (CubeSat Kit)", mass_note="unverified", fidelity="envelope_plus_features",
        cad_downloads=[{"format": "STEP/IGES/SolidWorks zips", "url": "http://www.cubesatkit.com/files/CAD/", "notes": "public CAD folder on cubesatkit.com"}], cost=cost(basis="quote")))

# AAC Clyde Space ZAPHOD structures (satsearch pages read 2026-11-08) and other vendors from the satsearch structures overview (masses only where the overview stated them)
for id, model, dims, mass, units in (("1u", "ZAPHOD 1U Structure", (100, 100, 113.5), 155, 1), ("3u", "ZAPHOD 3U Structure", (100, 100, 340.5), 394, 3), ("6u", "ZAPHOD 6U Structure", (226.3, 100, 340.5), 674, 3)):
    PARTS.append(part("aac_zaphod_" + id, "AAC Clyde Space " + model, "structures", "frame", "AAC Clyde Space", model, dims, mass,
        {"kind": "cubesat_frame", "units_z": units, "length_z": dims[2], "tolerance": 0.3} if id != "6u" else {"kind": "box", "x": 226.3, "y": 100, "z": 340.5},
        source("datasheet", "https://satsearch.co/products/aac-clyde-zaphod-" + id + "-structure", "satsearch listing of the AAC Clyde Space ZAPHOD " + id.upper() + " datasheet", ["dimensions_mm", "mass_g", "material", "thermal"], notes="Dimensions and mass from the listing (6U listed as 340.5 x 226.3 x 100 mm, i.e. a 6U with 3U-length rails). Aluminium 7075 and 6082 primary structure, -40 to 80 C, anodised rails, deployment switches, GEVS."), vendor_country="Sweden / UK", distributors=["direct", "satsearch"], status="in_production", material="aluminium 7075 and 6082", thermal={"operating_temperature_C": {"min": -40, "max": 80}}, fidelity="envelope_plus_features" if id != "6u" else "envelope", cost=cost(basis="quote")))
for id, vendor, country, model, dims, mass, units, url in (
    ("2ndspace_verse_02", "2NDSpace", "Italy", "VERSE-02 2U CubeSat Structure", (100, 100, 227.0), 195, 2, "https://satsearch.co/products/2ndspace-verse-02-2u-structure"),
    ("2ndspace_verse_03", "2NDSpace", "Italy", "VERSE-03 3U CubeSat Structure", (100, 100, 340.5), 290, 3, "https://satsearch.co/products/2ndspace-verse-03-3u-structure"),
    ("2ndspace_verse_06", "2NDSpace", "Italy", "VERSE-06 6U CubeSat Structure", (226.3, 100, 366), 690, 3, "https://satsearch.co/products/2ndspace-verse-06-6u-structure"),
    ("serenum_1u", "Serenum Space", "Czech Republic", "1-Unit Structure (1U)", (100, 100, 113.5), 137, 1, "https://satsearch.co/products/serenumspace-1-unit-structure-1u"),
    ("serenum_2u", "Serenum Space", "Czech Republic", "2-Unit Structure (2U)", (100, 100, 227.0), 269, 2, "https://satsearch.co/products/serenumspace-2-unit-structure-2u"),
    ("serenum_3u", "Serenum Space", "Czech Republic", "3-Unit Structure (3U)", (100, 100, 340.5), 396, 3, "https://satsearch.co/products/serenumspace-3-unit-structure-3u")):
    PARTS.append(part(id, vendor + " " + model, "structures", "frame", vendor, model, dims, mass,
        {"kind": "cubesat_frame", "units_z": units, "length_z": dims[2], "tolerance": 0.3} if dims[0] < 200 else {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]},
        source("unverified", url, "satsearch structures overview (mass) and listing", ["mass_g"], notes="Approximate mass from the satsearch overview; envelope assumed per CDS Rev 14.1 (not stated on the overview). Listing has the datasheet."), vendor_country=country, distributors=["direct", "satsearch"], status="in_production", dimensions_note="assumed per CDS", fidelity="envelope_plus_features" if dims[0] < 200 else "envelope", cost=cost(basis="quote")))

PARTS.append(part("gomspace_nanostruct_6u_mk2", "GomSpace NanoStruct 6U Mk2 structure (Al 7075, 665 g)", "structures", "frame", "GomSpace", "NanoStruct 6U Mk2", (226.3, 100, 340.5), 665, {"kind": "box", "x": 226.3, "y": 100, "z": 340.5},
    source("datasheet", "https://gomspace.com/wp-content/uploads/2025/09/gs-ds-nanostructure-6u-Mk2-1060779-12-EXT.pdf", "GomSpace NanoStruct 6U Mk2 datasheet DS 1060779", ["dimensions_mm", "mass_g", "material"], notes="340.5 x 226.3 x 100 mm with deployment switches stowed; ~665 g default (2 side frames at 306 g each with kill switches, 4 corner brackets at 10 g, screw/pin kit); mounting rings 14 g (A/B) and 24 g (YA/YB); M3 threaded rod 0.0495 g/mm. EN AW-7075-T7351, SurTec 650 chromitAL TCP MIL-DTL-5541F Type II Class 3, Helicoil inserts.", revision="1.2", date="2025-08-08"), vendor_country="Denmark", distributors=["direct"], status="in_production", material="aluminium EN AW-7075-T7351, SurTec 650 TCP finish, Helicoil inserts", fidelity="envelope", cost=cost(basis="quote")))

# NanoAvionics structural frames (product page read 2026-11-08: list prices, material; dimensions per CDS, masses estimated)
for id, units, dims, mass, price in (("6u", "6U", (226.3, 100, 366), 700, 5040), ("12u", "12U", (226.3, 226.3, 366), 1200, 10000)):
    PARTS.append(part("nanoavionics_frame_" + id, "NanoAvionics " + units + " CubeSat structural frame (7075-T7351, hard anodised)", "structures", "frame", "NanoAvionics (Kongsberg NanoAvionics)", units + " structural frame", dims, mass, {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]},
        source("unverified", "https://nanoavionics.com/cubesat-components/cubesat-structural-frame/", "NanoAvionics CubeSat structural frame product page", ["material", "cost"], notes="Price EUR " + str(price) + " per unit (MOQ 3, lead time 1-3 months), 7075-T7351 hard anodised, stainless inserts, PC/104, GEVS tested from the page. Dimensions and mass NOT listed: CDS envelope and an ESTIMATED mass are used."), vendor_country="Lithuania", distributors=["direct (nanoavionics.com)"], status="in_production", lead_time="1-3 months", dimensions_note="assumed per CDS", mass_note="estimate", material="aluminium 7075-T7351, hard anodised, stainless inserts", fidelity="envelope",
        cost=cost(value=price, currency="EUR", basis="list_price", source_url="https://nanoavionics.com/cubesat-components/cubesat-structural-frame/")))
