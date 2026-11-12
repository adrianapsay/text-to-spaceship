"""Small-satellite (non-CubeSat, microsat / ESPA class) parts added 2026-11-11.
Rule: only products whose vendor datasheet states outer dimensions and mass. Each record names the datasheet it was read from.
Photos and the datasheet PDFs are fetched by the laptop kit (pass 5c)."""
from parts_data._common import part, source, cost

PARTS = []

# ---- Blue Canyon Technologies reaction wheels (data sheet "Reaction Wheels 1_2025", read 2026-11-11)
BCT_WHEELS = "https://www.bluecanyontech.com/wp-content/uploads/Reaction-Wheels-1_2025.pdf"
BCT_NOTE = "Blue Canyon reaction wheel data sheet (2025): momentum, torque, mass, dimensions, zero-momentum power, supply voltage, RS-422, -20 to +60 C operating (-30 to +70 C survival). The sheet says values are for information only and subject to change."
for id, model, momentum, torque, mass, dims, power_zero, voltage_min, voltage_max in (
        ("rwp015", "RWp015", 0.015, 0.004, 130, (42, 42, 19), 1.0, 10, 14),
        ("rwp050", "RWp050", 0.050, 0.007, 240, (58, 58, 25), 1.0, 10, 14),
        ("rwp100", "RWp100", 0.100, 0.007, 330, (70, 70, 25), 1.0, 10, 14),
        ("rwp500", "RWp500", 0.500, 0.025, 860, (112, 124, 38), 6.0, 22, 34),
        ("rw1", "RW1", 1.0, 0.06, 1100, (112, 112, 55), 14.0, 28, 34),
        ("rw4", "RW4", 4.0, 0.25, 3200, (175, 175, 72), 10.0, 22, 34),
        ("rw8", "RW8", 8.0, 0.25, 4400, (193, 193, 84), 10.0, 22, 34)):
    PARTS.append(part("bct_" + id, "Blue Canyon Technologies " + model + " reaction wheel (" + str(momentum) + " Nms)", "adcs", "reaction_wheel", "Blue Canyon Technologies", model, dims, mass,
        {"kind": "reaction_wheel", "x": dims[0], "y": dims[1], "z": dims[2], "housing": "round" if id in ("rw4", "rw8") else "box"},
        source("datasheet", BCT_WHEELS, "Blue Canyon Technologies Reaction Wheels data sheet 1_2025", ["dimensions_mm", "mass_g", "adcs", "electrical", "thermal"], notes=BCT_NOTE + " Torque for RWp500 and larger is read from a scrambled text extraction; check against the PDF.", date="2025"),
        vendor_country="USA", distributors=["direct"], status="in_production", fidelity="envelope_plus_features", satellite_class="cubesat" if momentum <= 0.1 else "smallsat",
        adcs={"momentum_Nms": momentum, "max_torque_Nm": torque}, electrical={"voltage_V": {"min": voltage_min, "max": voltage_max}, "power_W": {"idle": power_zero}, "interfaces": ["RS-422"]},
        thermal={"operating_temperature_C": {"min": -20, "max": 60}}, cost=cost(basis="quote")))

# ---- Sodern Auriga star trackers (one-pagers read 2026-11-11)
AURIGA_SA = "https://sodern.com/wp-content/uploads/2023/12/2022-07-OnePager-Auriga-SA-v2.pdf"
AURIGA_CP = "https://sodern.com/wp-content/uploads/2023/12/2022-02-OnePager-Auriga-CP-v2.pdf"
AURIGA_PERFORMANCE = {"bias_deg": 0.017, "low_frequency_error_xy_z_arcsec_3sigma": [9, 51], "temporal_noise_xy_z_arcsec_3sigma": [11, 70], "update_rate_Hz": 10}
PARTS.append(part("sodern_auriga_sa_head", "Sodern Auriga-SA star tracker optical head (with baffle)", "adcs", "star_tracker", "Sodern", "Auriga-SA optical head", (66, 56, 94), 225,
    {"kind": "camera_box_lens", "x": 66, "y": 56, "z": 34, "lens_diameter": 46, "lens_length": 60},
    source("datasheet", AURIGA_SA, "Sodern Auriga-SA one-pager (2022-07, v2)", ["dimensions_mm", "mass_g", "adcs", "electrical", "thermal"], notes="Optical head 66 x 56 x 94 mm (height) and 225 g including baffle, 0.8 / 1.1 W typ/max, supplied by the electronic unit over SpaceWire (up to three heads per unit). -20 to +40 C operating. Body/baffle split of the CAD is schematic."),
    vendor_country="France", distributors=["direct", "CubeSatShop"], status="in_production", fidelity="envelope_plus_features", satellite_class="smallsat",
    adcs=AURIGA_PERFORMANCE, electrical={"power_W": {"nominal": 0.8, "peak": 1.1}, "interfaces": ["SpaceWire to the Auriga-SA electronic unit"]}, thermal={"operating_temperature_C": {"min": -20, "max": 40}}, cost=cost(basis="quote")))
PARTS.append(part("sodern_auriga_sa_electronics", "Sodern Auriga-SA star tracker electronic unit", "adcs", "star_tracker", "Sodern", "Auriga-SA electronic unit", (91, 117, 25), 315,
    {"kind": "box", "x": 91, "y": 117, "z": 25},
    source("datasheet", AURIGA_SA, "Sodern Auriga-SA one-pager (2022-07, v2)", ["dimensions_mm", "mass_g", "electrical", "thermal"], notes="Electronic unit 91 x 117 x 25 mm (height), 315 g, 2.5 / 3.4 W typ/max, 5 V +-5 %, RS422 UART 115200 baud output, 8 or 10 Hz."),
    vendor_country="France", distributors=["direct", "CubeSatShop"], status="in_production", fidelity="envelope", satellite_class="smallsat",
    electrical={"voltage_V": {"nominal": 5.0}, "power_W": {"nominal": 2.5, "peak": 3.4}, "interfaces": ["RS422 UART"]}, thermal={"operating_temperature_C": {"min": -20, "max": 40}}, cost=cost(basis="quote")))
PARTS.append(part("sodern_auriga_cp", "Sodern Auriga-CP star tracker camera head (processing on the host, with baffle)", "adcs", "star_tracker", "Sodern", "Auriga-CP", (66, 59, 94), 225,
    {"kind": "camera_box_lens", "x": 66, "y": 59, "z": 34, "lens_diameter": 46, "lens_length": 60},
    source("datasheet", AURIGA_CP, "Sodern Auriga-CP one-pager (2022-02, v2)", ["dimensions_mm", "mass_g", "adcs", "electrical", "thermal"], notes="66 x 59 x 94 mm (height) and 225 g including baffle, 0.8 / 1.1 W typ/max, 5 V +-10 %, SpaceWire 50 Mbps to the spacecraft processor which runs the star tracking software, up to 10 Hz. -20 to +40 C operating."),
    vendor_country="France", distributors=["direct", "CubeSatShop"], status="in_production", fidelity="envelope_plus_features", satellite_class="smallsat",
    adcs=AURIGA_PERFORMANCE, electrical={"voltage_V": {"nominal": 5.0}, "power_W": {"nominal": 0.8, "peak": 1.1}, "interfaces": ["SpaceWire"]}, thermal={"operating_temperature_C": {"min": -20, "max": 40}}, cost=cost(basis="quote")))

# ---- EnerSys ABSL battery (datasheet read 2026-11-11)
ABSL_8S16P = "https://www.enersys.com/49878d/globalassets/documents/product-documentation/absl/amer/amer-en-ds-absl_8s16p_0426_web.pdf"
PARTS.append(part("enersys_absl_8s16p", "EnerSys ABSL 8s16p Li-ion space battery (56 Ah, 28 V class)", "power", "battery", "EnerSys (ABSL)", "ABSL 8s16p", (364, 203, 98), 7800,
    {"kind": "box", "x": 364, "y": 203, "z": 98},
    source("datasheet", ABSL_8S16P, "EnerSys ABSL 8s16p datasheet (2026-04)", ["dimensions_mm", "mass_g", "electrical", "thermal"], notes="Nameplate 56 Ah / 1628 Wh, 24 to 33.6 V, 7.8 kg nominal, footprint 364 x 203 mm, height 98 mm, ABSL 18650 E35 cells, discharge -5 to 40 C, charge 0 to 40 C, non-operating -20 to 60 C."),
    vendor_country="United Kingdom / USA", distributors=["direct"], status="in_production", fidelity="envelope", satellite_class="smallsat",
    electrical={"chemistry": "Li-ion 18650 (ABSL E35)", "configuration": "8s16p", "energy_Wh": 1628, "capacity_mAh": 56000, "voltage_V": {"min": 24.0, "max": 33.6}},
    thermal={"operating_temperature_C": {"min": -5, "max": 40}, "charge_temperature_C": {"min": 0, "max": 40}}, cost=cost(basis="quote")))

# ---- Communications
XLINK_X = "https://www.cubesatshop.com/wp-content/uploads/2023/04/XLink-X-Datasheet-09.2022.pdf"
PARTS.append(part("iq_spacecom_xlink_x", "IQ spacecom XLink-X X-band SDR transceiver (S-band receive option)", "comms", "transceiver", "IQ spacecom (IQ Technologies for Earth and Space GmbH)", "XLink-X", (90, 65, 25.3), 200,
    {"kind": "box", "x": 90, "y": 65, "z": 25.3},
    source("datasheet", XLINK_X, "IQ spacecom XLink-X datasheet 09.2022", ["dimensions_mm", "mass_g", "rf", "electrical", "thermal"], notes="90 x 65 x 25.3 mm, 200 g incl. housing, <16 W Tx + Rx, 6-18 V or 28 V, Tx 8.025-8.400 GHz, Rx X 7.145-7.250 GHz or S 2.025-2.110 GHz, 2 kbps to 200 Mbps downlink, -30 to +60 C."),
    vendor_country="Germany", distributors=["direct", "CubeSatShop"], status="in_production", fidelity="envelope", satellite_class="cubesat_and_smallsat",
    rf={"band": "X (S receive option)", "frequency_MHz": [[8025, 8400]], "rx_frequency_MHz": [[7145, 7250], [2025, 2110]], "data_rate_bps": {"max": 200000000}},
    electrical={"voltage_V": {"min": 6, "max": 18}, "voltage_note": "6-18 V or 28 V version", "power_W": {"peak": 16}}, thermal={"operating_temperature_C": {"min": -30, "max": 60}}, cost=cost(basis="quote")))
CTT_524 = "https://l3harris.com/sites/default/files/2024-12/l3harris-ctt-524-spec-sheet.pdf"
PARTS.append(part("l3harris_ctt_524", "L3Harris C/TT-524 S/X-band transceiver (without diplexer)", "comms", "transceiver", "L3Harris", "C/TT-524", (218.4, 104.1, 116.8), 2950,
    {"kind": "box", "x": 218.4, "y": 104.1, "z": 116.8},
    source("datasheet", CTT_524, "L3Harris C/TT-524 S/X-band transceiver spec sheet (2024-12)", ["dimensions_mm", "mass_g", "rf", "electrical"], notes="8.6 L x 4.1 W x 4.6 H in (218.4 x 104.1 x 116.8 mm) and 2.95 kg without diplexer; 9.5 x 5.7 x 4.6 in and < 4.08 kg with diplexer. 22 to 36 VDC, Rx-only < 8 W. X-band transmit 8025-8500 MHz, S-band receive 2025-2110 MHz, 1 kbps to 6 Mbps (ground network) or 125 bps to 300 kbps (TDRSS). Operating temperature row is garbled in the text extraction (likely -20 to +60 C); check the PDF."),
    vendor_country="USA", distributors=["direct"], status="in_production", fidelity="envelope", satellite_class="smallsat",
    rf={"band": "X transmit / S receive", "frequency_MHz": [[8025, 8500]], "rx_frequency_MHz": [[2025, 2110]], "data_rate_bps": {"max": 6000000}},
    electrical={"voltage_V": {"min": 22, "max": 36}, "power_W": {"idle": 8}}, cost=cost(basis="quote")))

# ---- EnerSys ABSL CM series (EMEA/APAC datasheets 0722, read 2026-11-11). Cells: ABSL P20 Li-ion. Operating 0 to 40 C (thermal chamber only, per the sheet).
ABSL_CM = "https://integration.enersys.com/4964a0/globalassets/documents/product-documentation/absl/emea/"
for id, model, url, ah, wh, vmin, vmax, mass, dims in (
        ("cm58_8s1p", "ABSL CM58 8s1p P20 28V 2Ah", "https://integration.enersys.com/4964a0/globalassets/documents/product-documentation/absl/emea/emea_apac-en-ds-absl-cm58-8s1p-0722--web.pdf", 2, 59.2, 24.0, 33.6, 520, (105, 70, 74)),
        ("cm170_4s6p", "ABSL CM170 4s6p P20 14V 12Ah", "https://enersys.com/496008/globalassets/documents/product-documentation/absl/emea/emea_apac-en-ds-absl-cm170-4s6p-0722-web.pdf", 12, 178, 12.0, 16.8, 1600, (113, 132, 95)),
        ("cm230_8s4p", "ABSL CM230 8s4p P20 28V 8Ah", "https://integration.enersys.com/496413/globalassets/documents/product-documentation/absl/emea/emea_apac-en-ds-absl-cm230-8s4p-0722-web.pdf", 8, 236.8, 24.0, 33.6, 2050, (114, 168, 117)),
        ("cm520_8s9p", "ABSL CM520 8s9p P20 28V 18Ah", "https://integration.enersys.com/49601b/globalassets/documents/product-documentation/absl/emea/emea_apac-en-ds-absl-cm520-8s9p-0722-web.pdf", 18, 532.8, 24.0, 33.6, 4300, (209, 190, 117)),
        ("cm1040_8s18p", "ABSL CM1040 8s18p P20 28V 36Ah", "https://enersys.com/495fe7/globalassets/documents/product-documentation/absl/emea/emea_apac-en-ds-absl-cm1040-8s18p-0722-web.pdf", 36, 1066, 24.0, 33.6, 8800, (209, 362, 131)),
        ("cm2300_8s40p", "ABSL CM2300 8s40p P20 28V 80Ah", "https://www.enersys.com/496004/globalassets/documents/product-documentation/absl/emea/emea_apac-en-ds-absl-cm2300-8s40p-0722-web.pdf", 80, 2300, 24.0, 33.6, 20000, (260, 359, 177))):
    PARTS.append(part("enersys_absl_" + id, "EnerSys " + model + " Li-ion space battery", "power", "battery", "EnerSys (ABSL)", model, dims, mass,
        {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]},
        source("datasheet", url, "EnerSys " + model + " datasheet (EMEA/APAC, 07/2022)", ["dimensions_mm", "mass_g", "electrical", "thermal"], notes="Nameplate " + str(ah) + " Ah / " + str(wh) + " Wh, " + str(vmin) + " to " + str(vmax) + " V, measured mass " + str(mass / 1000) + " kg, footprint " + str(dims[0]) + " x " + str(dims[1]) + " mm, height " + str(dims[2]) + " mm, ABSL P20 cells. Operating 0 to 40 C (thermal chamber only)."),
        vendor_country="United Kingdom", distributors=["direct"], status="in_production", fidelity="envelope", satellite_class="smallsat",
        electrical={"chemistry": "Li-ion (ABSL P20 cells)", "configuration": id.split("_")[1], "energy_Wh": wh, "capacity_mAh": ah * 1000, "voltage_V": {"min": vmin, "max": vmax}},
        thermal={"operating_temperature_C": {"min": 0, "max": 40}}, cost=cost(basis="quote")))

# ---- Rocket Lab (Sinclair) larger reaction wheels (data sheets read 2026-11-11)
RL_RW04 = "https://www.rocketlab.co.nz/assets/Uploads/400-Nms-RW4-0.4-Data-Sheet.pdf"
RL_RW1 = "https://www.rocketlab.co.nz/assets/Uploads/1-Nms-RW4-1.0-Data-Sheet.pdf"
RL_RW12 = "https://www.rocketlab.co.nz/assets/Uploads/12-Nms-RW4-RW5-Data-Sheet-v3.pdf"
PARTS.append(part("rocketlab_rw04_heavy", "Rocket Lab RW-0.4 reaction wheel (0.4 Nms heavy rotor)", "adcs", "reaction_wheel", "Rocket Lab", "RW-0.4 (heavy rotor)", (103, 103, 46), 770,
    {"kind": "reaction_wheel", "x": 103, "y": 103, "z": 46, "housing": "round"},
    source("datasheet", RL_RW04, "Rocket Lab 400 mNms RW-0.4 data sheet", ["dimensions_mm", "mass_g", "adcs", "electrical", "thermal"], notes="46 mm high x 103 mm diameter (not including mounting feet), 770 g (0.4 Nms) / 600 g (0.2 Nms light rotor), +-100 mNm, 24-34 V (+75 V options), redundant RS-485, -40 to +70 C operating."),
    vendor_country="USA / Canada", distributors=["direct"], status="in_production", fidelity="envelope_plus_features", satellite_class="smallsat",
    adcs={"momentum_Nms": 0.4, "max_torque_Nm": 0.1}, electrical={"voltage_V": {"min": 24, "max": 34}, "interfaces": ["RS-485 (redundant)"]}, thermal={"operating_temperature_C": {"min": -40, "max": 70}}, cost=cost(basis="quote")))
PARTS.append(part("rocketlab_rw4_1p0", "Rocket Lab RW4-1.0 reaction wheel (1 Nms)", "adcs", "reaction_wheel", "Rocket Lab", "RW4-1.0", (154, 146, 45), 1380,
    {"kind": "reaction_wheel", "x": 154, "y": 146, "z": 45},
    source("datasheet", RL_RW1, "Rocket Lab 1 Nms RW4-1.0 data sheet", ["dimensions_mm", "mass_g", "adcs", "electrical", "thermal"], notes="154 x 146 x 45 mm, 1380 g, 100 mNm at 0.8 Nms (28 V), 5.3 W steady at 1 Nms, 43 W peak, 24-34 V (50 V max), redundant RS-485, -40 to +70 C operating."),
    vendor_country="USA / Canada", distributors=["direct"], status="in_production", fidelity="envelope_plus_features", satellite_class="smallsat",
    adcs={"momentum_Nms": 1.0, "max_torque_Nm": 0.1}, electrical={"voltage_V": {"min": 24, "max": 34}, "power_W": {"nominal": 5.3, "peak": 43}, "interfaces": ["RS-485 (redundant)"]}, thermal={"operating_temperature_C": {"min": -40, "max": 70}}, cost=cost(basis="quote")))
for id, model, voltage_min, voltage_max, idle in (("rw4_12", "RW4-12.0 (rad-hard)", 24, 34, 2.0), ("rw5_12", "RW5-12.0 (standard)", 30, 50, 1.6)):
    PARTS.append(part("rocketlab_" + id, "Rocket Lab " + model + " reaction wheel (12 Nms)", "adcs", "reaction_wheel", "Rocket Lab", model, (264, 264, 70), 5000,
        {"kind": "reaction_wheel", "x": 264, "y": 264, "z": 70, "housing": "round"},
        source("datasheet", RL_RW12, "Rocket Lab 12 Nms RW4/RW5 data sheet v3", ["dimensions_mm", "mass_g", "adcs", "electrical", "thermal"], notes="264 mm diameter x 70 mm height, 5 kg max, +-12 Nms, +-0.2 Nm, <38 W at 12 Nms steady state, CAN-FD and redundant RS-485, -20 to 60 C operating. Mass is the stated maximum."),
        vendor_country="USA / Canada", distributors=["direct"], status="in_production", fidelity="envelope_plus_features", satellite_class="smallsat",
        adcs={"momentum_Nms": 12, "max_torque_Nm": 0.2}, electrical={"voltage_V": {"min": voltage_min, "max": voltage_max}, "power_W": {"idle": idle, "nominal": 38}, "interfaces": ["CAN-FD", "RS-485 (redundant)"]}, thermal={"operating_temperature_C": {"min": -20, "max": 60}}, cost=cost(basis="quote")))

# ---- Terma star trackers (data sheets read 2026-11-11)
TERMA_T1 = "https://www.terma.com/media/d1ifyxd3/terma_t1_str_data_sheet.pdf"
TERMA_T3 = "https://www.terma.com/media/0m4hsarf/terma_t3_str_data_sheet.pdf"
TERMA_ACCURACY = {"bias_arcsec": 10, "spatial_error_fov_arcsec_3sigma": 2.1, "spatial_error_pixel_arcsec_3sigma": 1.3}
PARTS.append(part("terma_t1_optical_head", "Terma T1 star tracker optical head (no baffle)", "adcs", "star_tracker", "Terma", "T1 optical head", (92, 92, 68), 313,
    {"kind": "lens_barrel", "diameter": 92, "length": 68},
    source("datasheet", TERMA_T1, "Terma T1 star tracker data sheet", ["dimensions_mm", "mass_g", "adcs", "electrical", "thermal"], notes="Optical head footprint 92 mm diameter, height 68 mm, 313 g, 0.8 W at 5.0 V from the electrical unit, SpaceWire 80 MHz, -40 to +65 C (reduced performance above +30 C on sensor). Baffles are separate parts."),
    vendor_country="Denmark", distributors=["direct"], status="in_production", fidelity="envelope", satellite_class="smallsat",
    adcs=TERMA_ACCURACY, electrical={"voltage_V": {"nominal": 5.0}, "power_W": {"nominal": 0.8}, "interfaces": ["SpaceWire"]}, thermal={"operating_temperature_C": {"min": -40, "max": 65}}, cost=cost(basis="quote")))
PARTS.append(part("terma_t1_electrical_unit", "Terma T1 star tracker electrical unit (up to two optical heads)", "adcs", "star_tracker", "Terma", "T1 electrical unit", (100, 100, 40), 450,
    {"kind": "box", "x": 100, "y": 100, "z": 40},
    source("datasheet", TERMA_T1, "Terma T1 star tracker data sheet", ["dimensions_mm", "mass_g", "electrical", "thermal"], notes="100 x 100 x 40 mm, 450 g, 2.5 W excluding the optical head, redundant +28 V (20-36 V), redundant SpaceWire or RS422 to the spacecraft, -40 to +65 C operating."),
    vendor_country="Denmark", distributors=["direct"], status="in_production", fidelity="envelope", satellite_class="smallsat",
    electrical={"voltage_V": {"min": 20, "max": 36}, "power_W": {"nominal": 2.5}, "interfaces": ["SpaceWire", "RS422"]}, thermal={"operating_temperature_C": {"min": -40, "max": 65}}, cost=cost(basis="quote")))
for id, angle, diameter, height, mass in (("30deg", 30, 125, 165, 242), ("26deg", 26, 155, 213, 324)):
    PARTS.append(part("terma_t1_baffle_" + id, "Terma T1 star tracker baffle, " + str(angle) + " deg sun exclusion", "adcs", "star_tracker_baffle", "Terma", "T1 baffle " + str(angle) + " deg", (diameter, diameter, height), mass,
        {"kind": "radome_puck", "diameter": diameter, "length": height},
        source("datasheet", TERMA_T1, "Terma T1 star tracker data sheet", ["dimensions_mm", "mass_g"], notes="Baffle " + str(angle) + " deg: diameter " + str(diameter) + " mm, height " + str(height) + " mm, " + str(mass) + " g. Drawn as a solid of revolution envelope."),
        vendor_country="Denmark", distributors=["direct"], status="in_production", fidelity="envelope", satellite_class="smallsat", adcs={"sun_exclusion_angle_deg": angle}, cost=cost(basis="quote")))
PARTS.append(part("terma_t3", "Terma T3 star tracker (all-in-one, 37.5 deg baffle)", "adcs", "star_tracker", "Terma", "T3", (60, 60, 100), 350,
    {"kind": "camera_box_lens", "x": 60, "y": 60, "z": 24, "lens_diameter": 54, "lens_length": 76},
    source("datasheet", TERMA_T3, "Terma T3 star tracker data sheet", ["dimensions_mm", "mass_g", "adcs", "electrical", "thermal"], notes="60 x 60 x 100 mm, 350 g, 2 W, 4.5-5.5 V (7-33 V variant), RS422 (CAN variant), -35 to +65 C operating. Body/baffle split of the CAD is schematic."),
    vendor_country="Denmark", distributors=["direct"], status="in_production", fidelity="envelope_plus_features", satellite_class="cubesat_and_smallsat",
    adcs=TERMA_ACCURACY, electrical={"voltage_V": {"min": 4.5, "max": 5.5}, "power_W": {"nominal": 2.0}, "interfaces": ["RS422", "CAN (variant)"]}, thermal={"operating_temperature_C": {"min": -35, "max": 65}}, cost=cost(basis="quote")))

# ---- Jena-Optronik ASTRO APS (data sheet read 2026-11-11)
PARTS.append(part("jenaoptronik_astro_aps", "Jena-Optronik ASTRO APS star sensor (with baffle)", "adcs", "star_tracker", "Jena-Optronik", "ASTRO APS", (154, 154, 237), 2000,
    {"kind": "camera_box_lens", "x": 154, "y": 154, "z": 90, "lens_diameter": 80, "lens_length": 147, "baffle_diameter": 150},
    source("datasheet", "https://jena-optronik.de/tl_files/pdf/Data Sheet ASTRO APS.pdf", "Jena-Optronik ASTRO APS data sheet", ["dimensions_mm", "mass_g", "adcs", "electrical", "thermal"], notes="154 x 154 x 237 mm including baffle, approx. 2 kg including baffle, GEO shielding, DC/DC converter and MIL-1553. <6 W (RS422 <5 W) with Peltier cooler off, 28 V nominal (50/100 V options), random error <1 arcsec cross-boresight, bias <5 arcsec, -30 to +60 C operational. Body/baffle split of the CAD is schematic."),
    vendor_country="Germany", distributors=["direct"], status="in_production", fidelity="envelope_plus_features", satellite_class="smallsat",
    adcs={"random_error_arcsec_1sigma": 1, "bias_arcsec": 5}, electrical={"voltage_V": {"nominal": 28}, "power_W": {"nominal": 5, "peak": 12}, "interfaces": ["RS422", "MIL-STD-1553B (option)"]}, thermal={"operating_temperature_C": {"min": -30, "max": 60}}, cost=cost(basis="quote")))

# ---- Separation system and propulsion
PARTS.append(part("beyondgravity_pas_381s", "Beyond Gravity PAS 381S clamp-band separation system (15 in ESPA interface)", "mechanisms", "separation_system", "Beyond Gravity", "PAS 381S", (381, 381, 79), 3700,
    {"kind": "tube", "outer_diameter": 381, "inner_diameter": 341, "length": 79},
    source("datasheet", "https://www.beyondgravity.com/sites/default/files/media_document/2024-01/Beyond-Gravity-PAS-381S-Separation-System.pdf", "Beyond Gravity PAS 381S separation system data sheet", ["dimensions_mm", "mass_g", "mechanism"], notes="381 mm (15 in) ESPA interface diameter, 24 x 1/4 in bolts per ring, height 79 mm including springs and both rings, 3.7 kg total (separated mass 0.98 kg), low-shock clamp band released by CBOD-LT, 4 to 24 springs of 1.1 J. Ring outer diameter is not given; drawn at the 381 mm interface diameter with a 20 mm wall."),
    vendor_country="Sweden", distributors=["direct"], status="in_production", fidelity="envelope", satellite_class="smallsat",
    mechanism={"actuator_type": "clamp band (CBOD-LT release)", "interface_diameter_mm": 381, "spring_energy_J_each": 1.1, "springs": "4 to 24", "shock_g": 100}, cost=cost(basis="quote")))
PARTS.append(part("moog_monoprop_module_baseline", "Moog monopropellant propulsion module (10 cm baseline)", "propulsion", "propulsion_module", "Moog", "Monopropellant propulsion module (baseline)", (100, 100, 100), 1010,
    {"kind": "thruster_box_nozzle", "x": 100, "y": 100, "z": 90, "nozzle_diameter": 12, "nozzle_length": 10, "nozzle_count": 2},
    source("datasheet", "https://www.moog.com/content/dam/moog/literature/sdg/space/propulsion/moog-monopropellant-propulsion-module-datasheet.pdf", "Moog monopropellant propulsion module data sheet", ["dimensions_mm", "mass_g", "propulsion", "electrical"], notes="10 x 10 x 10 cm baseline (scalable to 24 x 24 x 24 cm), 1.01 kg wet, 150 cc tank, 0.1 to 1 N thrust (0.5 N baseline), 2 x 22.5 W per thruster, 500 N s total impulse, 59 m/s delta-v (vehicle not stated). Nozzle features of the CAD are schematic."),
    vendor_country="USA", distributors=["direct"], status="in_production", fidelity="envelope_plus_features", satellite_class="cubesat_and_smallsat",
    propulsion={"type": "monopropellant", "thrust_N": {"min": 0.1, "max": 1.0, "nominal": 0.5}, "total_impulse_Ns": 500, "tank_volume_cc": 150, "delta_v_m_s": 59}, electrical={"power_W": {"peak": 45}}, cost=cost(basis="quote")))
