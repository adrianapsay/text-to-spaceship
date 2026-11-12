"""Parts added 2026-11-11 (second batch) from vendor datasheets found by broad web search, one PDF read at a time (URL recorded per part).
Only datasheets that state outer dimensions and mass are used."""
from parts_data._common import part, source, cost

PARTS = []


def add(id, name, category, subcategory, vendor, model, dims, mass, shape, url, title, notes, fields=("dimensions_mm", "mass_g"), **extra):
    extra.setdefault("status", "in_production")
    extra.setdefault("fidelity", "envelope_plus_features")
    extra.setdefault("distributors", ["direct"])
    extra.setdefault("cost", cost(basis="quote"))
    PARTS.append(part(id, name, category, subcategory, vendor, model, dims, mass, shape, source("datasheet", url, title, list(fields), notes=notes, date="2026-11-11"), **extra))


# ---- sun sensors
add("gomspace_nanosense_fss", "GomSpace NanoSense Fine Sun Sensor (I2C, 60 deg half angle)", "adcs", "sun_sensor", "GomSpace", "NanoSense FSS", (22, 11, 5), 2.2,
    {"kind": "sun_sensor", "x": 22, "y": 11, "z": 5, "aperture_diameter": 3},
    "https://gomspace.com/UserFiles/Subsystems/datasheet/gs-ds-nanosense-fss-30.pdf", "GomSpace NanoSense Fine Sun Sensor data sheet",
    "Sensor housing 22 x 11 x 5 mm (elevator 22 x 11 x 1.3 mm not included), 2.2 g, +-0.5 deg (3 sigma) inside 45 deg FOV, half angle 60 deg, 3.3 V, 3.5 mA sampling, I2C slave 0x05, -40 to 100 C.",
    fields=("dimensions_mm", "mass_g", "adcs", "electrical", "thermal"), vendor_country="Denmark", protrusions="1.3 mm elevator plate not included",
    adcs={"accuracy_deg": 0.5, "fov_half_angle_deg": 60}, electrical={"voltage_V": {"nominal": 3.3}, "current_mA": 3.5, "interfaces": ["I2C"]}, thermal={"operating_temperature_C": {"min": -40, "max": 100}})
for id, model, height, mass, fov, accuracy in (("voyager_vantagesun_medium_mss01", "VantageSun Medium MSS-01", 24.31, 38.5, 48, 0.4),
                                                ("voyager_vantagesun_medium_mss02", "VantageSun Medium MSS-02 / MSS-03", 11.61, 33.5, 120, 0.6)):
    add(id, "Voyager " + model + " analog fine sun sensor (" + str(fov) + " deg full angle)", "adcs", "sun_sensor", "Voyager Technologies", model, (34.93, 34.93, height), mass,
        {"kind": "lens_barrel", "diameter": 19.05, "length": height, "flange_diameter": 34.93, "flange_thickness": 2.0},
        "https://voyagertechnologies.com/wp-content/uploads/2026/04/VantageSun-Medium-data-sheet.pdf", "Voyager VantageSun Medium data sheet",
        "Housing 19.05 mm diameter, flange 34.93 mm across, sensor height " + str(height) + " mm, " + str(mass) + " g including flying leads, " + str(fov) + " deg full-angle circular FOV, <" + str(accuracy) + " deg accuracy inside 24 deg, passive (four 0 to 4.5 mA current outputs), 1.27 m flying leads, -40 to +80 C. Flange thickness is drawn as 2 mm in the CAD (not stated).",
        fields=("dimensions_mm", "mass_g", "adcs", "electrical", "thermal"), vendor_country="USA", mass_note="includes flying leads",
        adcs={"accuracy_deg": accuracy, "fov_full_angle_deg": fov}, electrical={"power_W": {"nominal": 0}, "interfaces": ["4 analog current outputs"]}, thermal={"operating_temperature_C": {"min": -40, "max": 80}})

# ---- cells
add("saft_mp176065_xtd", "Saft MP 176065 xtd prismatic Li-ion cell (6.8 Ah)", "power", "battery_cell", "Saft", "MP 176065 xtd", (19.8, 61, 65), 155,
    {"kind": "cell_pouch", "x": 19.8, "y": 61, "z": 65},
    "https://docs.rs-online.com/32de/0900766b8056b890.pdf", "Saft MP 176065 data sheet (RS Components copy)",
    "Thickness max at end of life 19.8 mm, width max 61 mm, height max 65 mm, typical weight 155 g, 6.8 Ah at 4.2 V, 3.75 V nominal, charge -20 to +60 C, discharge -50 to +60 C.",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal"), vendor_country="France", distributors=["RS Components", "direct"], cost=cost(basis="distributor"),
    electrical={"capacity_Ah": 6.8, "voltage_V": {"nominal": 3.75, "max": 4.2}}, thermal={"operating_temperature_C": {"min": -50, "max": 60}})

# ---- motors
add("faulhaber_2232_sr", "Faulhaber 2232 SR precious-metal-commutated DC micromotor (22 mm)", "mechanisms", "motor", "Faulhaber", "2232 U ... SR", (22, 22, 32), 62,
    {"kind": "cylinder", "diameter": 22, "length": 32},
    "https://www.im-tek.com/docs/faulhaber-2232u006sr-dc-micromotor-658229.pdf", "Faulhaber series 2232 SR data sheet",
    "22 mm diameter, 32 mm body length (the series code 2232 is diameter 22 mm, length 32 mm), 2 mm shaft (not in the envelope), mass 62 g, 6 to 24 V variants, stall torque about 46 to 59 mNm, no-load speed about 7100 rpm, -30 to +85 C (optional -55 to +125 C).",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal"), vendor_country="Germany", distributors=["RS Components", "Digi-Key", "direct"], cost=cost(basis="distributor"), protrusions="2 mm shaft",
    electrical={"voltage_V": {"min": 6, "max": 24}}, thermal={"operating_temperature_C": {"min": -30, "max": 85}}, mechanism={"actuator_type": "brushed DC motor", "stall_torque_mNm": 46.7})

# ---- ThrustMe NPT30-I2 1.5U (same data sheet as the 1U in web_2026_11_11)
add("thrustme_npt30_i2_1p5u", "ThrustMe NPT30-I2 1.5U iodine gridded ion propulsion system", "propulsion", "electric_thruster", "ThrustMe", "NPT30-I2 1.5U", (93, 93, 155), 1700,
    {"kind": "electric_thruster", "x": 93, "y": 93, "z": 145, "emitter_diameter": 40, "emitter_length": 10},
    "https://thrustme.fr/base/stock/ProductBannerFiles/2_thrustme-npt30-i2.pdf", "ThrustMe NPT30-I2 data sheet",
    "93 x 93 x 155 mm, 1.7 kg total wet mass, thrust 0.3 to 1.1 mN, Isp up to 2400 s, 35 to 65 W, total impulse up to 9500 Ns. Dry mass not stated.",
    fields=("dimensions_mm", "mass_g", "propulsion", "electrical"), vendor_country="France", mass_note="wet mass (iodine loaded)",
    propulsion={"type": "gridded ion (iodine)", "thrust_mN": {"min": 0.3, "max": 1.1}, "isp_s": 2400, "total_impulse_Ns": 9500}, electrical={"power_W": {"min": 35, "max": 65}})

# ---- inertial sensors
for id, model, mass, power, bias, url, title in (
        ("sensonor_stim210", "STIM210", 52, 1.5, 0.3, "https://www.safran-group.com/sites/default/files/2022-05/safran-sensing-technologies-ts1545r20-stim210-datasheet.pdf", "Safran Sensonor STIM210 data sheet TS1545 rev 20"),
        ("sensonor_stim318", "STIM318", 57, 1.8, 0.3, "https://sensonor.azurewebsites.net/media/0cya54gd/ts1657-r8-datasheet-stim318.pdf", "Safran Sensonor STIM318 data sheet TS1657 rev 8")):
    add(id, "Safran Sensonor " + model + (" 3-axis gyro module" if model == "STIM210" else " tactical-grade IMU"), "adcs", "gyroscope" if model == "STIM210" else "imu", "Safran Sensonor", model, (38.6, 44.8, 21.5), mass,
        {"kind": "module_box", "x": 38.6, "y": 44.8, "z": 21.5},
        url, title, "38.6 x 44.8 x 21.5 mm, " + str(mass) + " g, +-400 deg/s, bias instability " + str(bias) + " deg/h (Allan variance, 25 C), single 5 V supply (4.5 to 5.5 V), " + str(power) + " W, RS422, -40 to +85 C.",
        fields=("dimensions_mm", "mass_g", "adcs", "electrical", "thermal"), vendor_country="Norway", distributors=["direct", "distributors"],
        adcs={"gyro_range_deg_s": 400, "gyro_bias_stability_deg_h": bias}, electrical={"voltage_V": {"min": 4.5, "nominal": 5.0, "max": 5.5}, "power_W": {"nominal": power}, "interfaces": ["RS422"]}, thermal={"operating_temperature_C": {"min": -40, "max": 85}})

# ---- GNSS receiver modules (commercial)
add("ublox_neo_m9n", "u-blox NEO-M9N GNSS receiver module (4 constellations)", "adcs", "gnss_receiver", "u-blox", "NEO-M9N", (12.2, 16.0, 2.4), 1.0,
    {"kind": "box", "x": 12.2, "y": 16.0, "z": 2.4},
    "https://content.u-blox.com/sites/default/files/NEO-M9N_ProductSummary_UBX-19027207.pdf", "u-blox NEO-M9N product summary UBX-19027207",
    "12.2 x 16.0 x 2.4 mm 24-pin LCC, 1.0 g, 2.7 to 3.6 V, 36 mA at 3.0 V (4 GNSS), UART / USB / SPI / I2C, -40 to +85 C. Commercial module, not space qualified.",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal"), vendor_country="Switzerland", distributors=["Digi-Key", "Mouser", "direct"], cost=cost(basis="distributor"),
    electrical={"voltage_V": {"min": 2.7, "max": 3.6}, "current_mA": 36, "interfaces": ["UART", "USB", "SPI", "I2C"]}, thermal={"operating_temperature_C": {"min": -40, "max": 85}})
add("septentrio_mosaic_x5", "Septentrio mosaic-X5 multi-band GNSS receiver module", "adcs", "gnss_receiver", "Septentrio", "mosaic-X5", (31, 31, 4), 6.8,
    {"kind": "box", "x": 31, "y": 31, "z": 4},
    "https://components101.com/sites/default/files/2020-09/Mosaic-X5-Datasheet.pdf", "Septentrio mosaic-X5 data sheet",
    "31 x 31 x 4 mm, 6.8 g, 0.6 W typical / 1.1 W max, 3.3 V +-5 %, 4 UART, Ethernet, USB, SDIO, CAN, PPS, -40 to +85 C. Commercial module, not space qualified.",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal"), vendor_country="Belgium", distributors=["Digi-Key", "direct"], cost=cost(basis="distributor"),
    electrical={"voltage_V": {"nominal": 3.3}, "power_W": {"nominal": 0.6, "peak": 1.1}, "interfaces": ["UART", "Ethernet", "USB", "SDIO", "CAN"]}, thermal={"operating_temperature_C": {"min": -40, "max": 85}})

# ---- cells and cameras (commercial)
add("lg_inr18650_mj1", "LG INR18650 MJ1 cylindrical Li-ion cell (3500 mAh)", "power", "cell", "LG Energy Solution", "INR18650 MJ1", (18.65, 18.65, 65.3), 49.0,
    {"kind": "cell_18650", "diameter": 18.65, "length": 65.3},
    "https://www.mikrocontroller.net/attachment/667554/30708_datasheet.pdf", "LG INR18650 MJ1 product specification",
    "Diameter 18.5 mm (max 18.65), height 65.1 mm (max 65.3); the envelope uses the maxima. Weight approx. max 49.0 g, 3500 mAh nominal, 3.635 V average, charge 0 to 45 C, discharge -20 to 60 C.",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal"), vendor_country="South Korea", distributors=["distributors"], cost=cost(basis="distributor"), mass_note="maximum per specification",
    electrical={"capacity_Ah": 3.5, "voltage_V": {"nominal": 3.635, "max": 4.2}}, thermal={"operating_temperature_C": {"min": -20, "max": 60}})
add("flir_boson_core", "Teledyne FLIR Boson LWIR thermal camera core (no lens)", "payload", "camera", "Teledyne FLIR", "Boson 320 / 640 core", (21, 21, 11), 7.5,
    {"kind": "module_box", "x": 21, "y": 21, "z": 11},
    "https://groupgets-files.s3.amazonaws.com/boson/documents/Boson%20datasheet,%20102-2013-40,%20Rev%20340.pdf", "Teledyne FLIR Boson data sheet 102-2013-40 rev 340",
    "21 x 21 x 11 mm (lens-less, shutter-less 320 and 640 engines), as light as 7.5 g, 0.5 to 1.55 W at 3.3 V, 320 x 256 or 640 x 512, CMOS or USB3 video, UART or USB control, -40 to +80 C. A lens adds length and mass.",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal", "payload"), vendor_country="USA", distributors=["distributors", "direct"], cost=cost(basis="distributor"), mass_note="lower bound (as light as 7.5 g, configuration dependent)",
    electrical={"voltage_V": {"nominal": 3.3}, "power_W": {"min": 0.5, "max": 1.55}, "interfaces": ["CMOS video", "USB3", "UART"]}, payload={"type": "LWIR microbolometer", "resolution_px": [640, 512]}, thermal={"operating_temperature_C": {"min": -40, "max": 80}})

for id, model, mass, resolution in (("flir_lepton_2p5", "Lepton 2.5", 1.02, [80, 60]), ("flir_lepton_3p1r", "Lepton 3.1R", 1.0, [160, 120]), ("flir_lepton_3p5", "Lepton 3.5", 0.9, [160, 120])):
    add(id, "Teledyne FLIR " + model + " LWIR micro thermal camera module", "payload", "camera", "Teledyne FLIR", model, (11.5, 12.7, 6.9), mass,
        {"kind": "camera_box_lens", "x": 11.5, "y": 12.7, "z": 5.0, "lens_diameter": 7.0, "lens_length": 1.9},
        "https://www.mouser.com/catalog/specsheets/Teledyne_Lepton_Series_7-28-23.pdf", "Teledyne FLIR Lepton series data sheet (7-28-23)",
        "11.5 x 12.7 x 6.9 mm without socket (11.8 x 12.7 x 7.2 mm with socket), " + str(mass) + " g without socket, " + str(resolution[0]) + " x " + str(resolution[1]) + " pixels, 150 mW operating (650 mW during shutter), video over SPI, CCI (I2C-like) control. The lens boss height inside the 6.9 mm is drawn from the photo, not stated.",
        fields=("dimensions_mm", "mass_g", "electrical", "payload"), vendor_country="USA", distributors=["Digi-Key", "Mouser", "GroupGets"], cost=cost(basis="distributor"),
        electrical={"power_W": {"nominal": 0.15, "peak": 0.65}, "interfaces": ["SPI video", "CCI (I2C)"]}, payload={"type": "LWIR microbolometer", "resolution_px": resolution})
add("novatel_imu_kvh1750", "NovAtel IMU-KVH1750 (KVH 1750 fibre-optic IMU in NovAtel enclosure)", "adcs", "imu", "NovAtel / KVH", "IMU-KVH1750", (88.9, 88.9, 73.7), 700,
    {"kind": "cylinder", "diameter": 88.9, "length": 73.7},
    "https://hexagondownloads.blob.core.windows.net/public/Novatel/assets/Documents/Papers/IMU-P-1750/IMU-P-1750.pdf", "NovAtel IMU-P1750 product sheet",
    "88.9 mm diameter x 73.7 mm high, 0.7 kg, gyro bias instability 0.05 deg/h, 9 to 36 VDC, 8 W max, RS-422, 15-pin Micro-D, -40 to +75 C.",
    fields=("dimensions_mm", "mass_g", "adcs", "electrical", "thermal"), vendor_country="Canada / USA",
    adcs={"gyro_bias_stability_deg_h": 0.05}, electrical={"voltage_V": {"min": 9, "max": 36}, "power_W": {"peak": 8}, "interfaces": ["RS-422"]}, thermal={"operating_temperature_C": {"min": -40, "max": 75}})
add("basler_dart_daa1920_160um", "Basler dart daA1920-160um USB3 board-level camera (S-mount)", "payload", "camera", "Basler", "daA1920-160um", (29.3, 29, 19.9), 15,
    {"kind": "camera_box_lens", "x": 29.3, "y": 29, "z": 8, "lens_diameter": 16, "lens_length": 11.9},
    "https://resources.ampheo.com/static/datasheets/basler/108230.pdf", "Basler dart daA1920-160um (S-mount) data sheet",
    "19.9 x 29.3 x 29 mm (L x W x H), 15 g typical, 1920 x 1200 px, USB 3.0, 1.8 W typical, 0 to 50 C. The S-mount boss proportions are drawn from the photo; the outer size is the datasheet's.",
    fields=("dimensions_mm", "mass_g", "electrical", "payload", "thermal"), vendor_country="Germany", distributors=["Basler shop", "distributors"], cost=cost(basis="distributor"),
    electrical={"power_W": {"nominal": 1.8}, "interfaces": ["USB 3.0"]}, payload={"type": "monochrome CMOS", "resolution_px": [1920, 1200]}, thermal={"operating_temperature_C": {"min": 0, "max": 50}})

add("calian_tw2710", "Calian (Tallysman) TW2710 single-band GNSS antenna (magnet mount)", "adcs", "gnss_antenna", "Calian (Tallysman)", "TW2710", (57, 57, 16), 110,
    {"kind": "radome_puck", "diameter": 57, "length": 16},
    "https://sites.calian.com/app/uploads/sites/8/2024/07/Calian%C2%AE-TW2710-Datasheet.pdf", "Calian TW2710 data sheet",
    "57 mm diameter x 16 mm high, 110 g, 1559 to 1606 MHz, LNA gain 28 dB typical, 2.5 to 16 VDC, 12 mA typical, -40 to +85 C. Commercial antenna, not space qualified.",
    fields=("dimensions_mm", "mass_g", "rf", "electrical", "thermal"), vendor_country="Canada", distributors=["Digi-Key", "Mouser", "direct"], cost=cost(basis="distributor"),
    rf={"band": "GNSS L1 / E1 / B1 / G1", "frequency_MHz": [[1559, 1606]], "lna_gain_dB": 28, "antenna_type": "active patch, radome"}, electrical={"voltage_V": {"min": 2.5, "max": 16}, "current_mA": 12}, thermal={"operating_temperature_C": {"min": -40, "max": 85}})
add("ettus_usrp_b205mini_i", "Ettus Research USRP B205mini-i 1x1 software-defined radio board", "comms", "sdr", "Ettus Research (NI) / Digilent", "USRP B205mini-i", (83.3, 50.8, 8.4), 24.0,
    {"kind": "pc104_board", "x": 83.3, "y": 50.8, "z": 1.6, "components_height": 6.8, "hole_diameter": 2.5},
    "https://www.mouser.lt/pdfDocs/ProductOverview_Digilent-USRP-B205mini-i-Software-Defined-Radio-Platform.pdf", "Digilent USRP B205mini-i product overview",
    "83.3 x 50.8 x 8.4 mm board, 24.0 g, 70 MHz to 6 GHz, >10 dBm output, 5 V USB power, USB 3.0, GPIO, JTAG, 10 MHz / PPS inputs. Commercial board, not space qualified.",
    fields=("dimensions_mm", "mass_g", "rf", "electrical"), vendor_country="USA", distributors=["Digilent", "Mouser", "Digi-Key"], cost=cost(basis="distributor"),
    rf={"band": "70 MHz to 6 GHz", "frequency_MHz": [[70, 6000]], "tx_power_dBm": 10}, electrical={"voltage_V": {"nominal": 5.0}, "interfaces": ["USB 3.0", "GPIO", "JTAG"]})

# ---- EBAD (TiNi) shape-memory release mechanisms: EBAD Space Mechanisms catalog (2023) and the TiNi Pin Puller sheet (2022). Inches converted to mm.
EBAD_CATALOG = "https://www.ebad.com/wp-content/uploads/2023/08/SPACE_MECH_68pgPlusCover_CATALOG_DigitalOnly_FINAL_7-25-2023.pdf"
EBAD_PIN_PULLER = "https://www.ebad.com/wp-content/uploads/2022/04/TiNi_Pin_Puller_released_3-18-22.pdf"
INCH = 25.4
for model, mass, length_in, diameter_in, hole_in, load_lbf in (("FC6", 110, 1.940, 1.225, 0.381, 6000), ("FC8", 175, 2.120, 1.400, 0.520, 9600), ("FB12", 350, 2.460, 1.975, 0.762, 26200), ("FD04", 10, 0.500, 0.450, 0.116, 150)):
    length, diameter, hole = round(length_in * INCH, 1), round(diameter_in * INCH, 1), round(hole_in * INCH, 1)
    add("ebad_frangibolt_" + model.lower(), "EBAD TiNi " + ("MINI " if model == "FD04" else "") + "Frangibolt " + model + " shape-memory release actuator", "mechanisms", "release_actuator", "Ensign-Bickford Aerospace & Defense (EBAD)", "TiNi Frangibolt " + model, (diameter, diameter, length), mass,
        {"kind": "tube", "outer_diameter": diameter, "inner_diameter": hole, "length": length}, EBAD_CATALOG, "EBAD Space Mechanisms catalog (7-25-2023), TiNi Frangibolt actuators",
        "Compressed length " + str(length_in) + " in, diameter " + str(diameter_in) + " in, thru-hole " + str(hole_in) + " in, mass " + str(mass) + " g, max load support " + str(load_lbf) + " lbf.",
        fields=("dimensions_mm", "mass_g", "mechanism"), vendor_country="USA", material="NiTi shape-memory alloy actuator, titanium fastener",
        mechanism={"actuator_type": "shape_memory_alloy (Frangibolt)", "max_load_N": round(load_lbf * 4.448)})
for model, mass, height_in, diameter_in, load_lbf in (("E250", 75, 2.195, 1.85, 250), ("E500", 100, 2.475, 2.1, 500), ("E1000", 160, 2.95, 2.35, 1000), ("E2000", 300, 3.93, 3.00, 2000), ("E4000", 530, 4.8, 3.825, 4000)):
    height, diameter = round(height_in * INCH, 1), round(diameter_in * INCH, 1)
    add("ebad_tini_erm_" + model.lower(), "EBAD TiNi Ejector Release Mechanism " + model + " (hold-down and release)", "mechanisms", "release_actuator", "Ensign-Bickford Aerospace & Defense (EBAD)", "TiNi ERM " + model, (diameter, diameter, height), mass,
        {"kind": "cylinder", "diameter": diameter, "length": height}, EBAD_CATALOG, "EBAD Space Mechanisms catalog (7-25-2023), TiNi Ejector Release Mechanism",
        "Height with coupler " + str(height_in) + " in, max diameter with flange " + str(diameter_in) + " in, mass " + str(mass) + " g, max release load " + str(load_lbf) + " lbf, function time 100 ms max at 23 C. The envelope is a cylinder of the flange diameter and the height with coupler.",
        fields=("dimensions_mm", "mass_g", "mechanism"), vendor_country="USA",
        mechanism={"actuator_type": "shape_memory_alloy release (ERM)", "max_load_N": round(load_lbf * 4.448), "actuation_time_s": 0.1})
add("ebad_tini_microlatch_ml50", "EBAD TiNi Microlatch ML50 (hold-down and release)", "mechanisms", "release_actuator", "Ensign-Bickford Aerospace & Defense (EBAD)", "TiNi Microlatch ML50", (25.4, 25.4, 16.5), 15,
    {"kind": "cylinder", "diameter": 25.4, "length": 16.5}, EBAD_CATALOG, "EBAD Space Mechanisms catalog (7-25-2023), TiNi Microlatch",
    "Height with coupler 0.65 in, max diameter with flange 1.00 in, mass 15 g, release load 50 lbf, 120 ms max at 1.75 A.", fields=("dimensions_mm", "mass_g", "mechanism"), vendor_country="USA",
    mechanism={"actuator_type": "shape_memory_alloy release (Microlatch)", "max_load_N": 222, "actuation_time_s": 0.12}, electrical={"current_A": 1.75})
for model, mass, height_in, diameter_in, load_lbf, current in (("P5", 18, 1.25, 1.25, 5, "0.5 to 2"), ("P10", 30, 1.625, 1.25, 10, "0.4 to 1.5"), ("P50", 75, 2.54, 1.8, 50, "1.25 to 4.5"), ("P100", 150, 3.50, 2.00, 100, "2.25 to 6.5"), ("P1000", 360, 4.255, 2.55, 1000, "2.25 to 6.5")):
    height, diameter = round(height_in * INCH, 1), round(diameter_in * INCH, 1)
    add("ebad_tini_pin_puller_" + model.lower(), "EBAD TiNi Pin Puller " + model + " (shape-memory)", "mechanisms", "pin_puller", "Ensign-Bickford Aerospace & Defense (EBAD)", "TiNi Pin Puller " + model, (diameter, diameter, height), mass,
        {"kind": "cylinder", "diameter": diameter, "length": height}, EBAD_PIN_PULLER, "EBAD TiNi Pin Puller data sheet (3-18-22)",
        "Height before retraction " + str(height_in) + " in, max diameter with flange " + str(diameter_in) + " in, mass " + str(mass) + " g, max pull load " + str(load_lbf) + " lbf, operating current " + current + " A.",
        fields=("dimensions_mm", "mass_g", "mechanism", "electrical"), vendor_country="USA",
        mechanism={"actuator_type": "shape_memory_alloy pin puller", "max_load_N": round(load_lbf * 4.448)}, electrical={"current_A_range": current})

# ---- space-grade DC-DC converters
SMHF_SHEET = "https://static.datasheets.com/doc/14462600-interpoint-smhf2805s-kl-ds.pdf"
for suffix, label, length_in in (("", "non-flanged", 1.460), ("_flanged", "flanged", 2.005)):
    length = round(length_in * 25.4, 2)
    add("interpoint_smhf_dcdc" + suffix, "Crane Interpoint SMHF space DC-DC converter, 15 W, " + label + " case", "power", "dc_dc_converter", "Crane Aerospace & Electronics (Interpoint)", "SMHF28xx (" + label + ")", (length, 28.70, 8.38), 30,
        {"kind": "box", "x": length, "y": 28.70, "z": 8.38}, SMHF_SHEET, "Crane Interpoint SMHF series data sheet",
        "Maximum package " + str(length_in) + " x 1.130 x 0.330 in (" + str(length) + " x 28.70 x 8.38 mm), 30 g maximum, up to 15 W (3.3 V 8 W, 5 V 12 W, 12/15 V 15 W; duals +-5/12/15 V), 16 to 40 VDC input, 50 V transient. Models SMHF283R3S, 2805S, 2812S, 2815S, 2805D, 2812D, 2815D share the case.",
        fields=("dimensions_mm", "mass_g", "electrical"), vendor_country="USA", mass_note="maximum per data sheet",
        electrical={"voltage_V": {"min": 16, "nominal": 28, "max": 40}, "power_W": {"peak": 15}, "outputs": ["3.3 V", "5 V", "12 V", "15 V", "+-5 V", "+-12 V", "+-15 V"]})
add("vpt_svpl3r306sg", "VPT SVPL3R306SG space point-of-load DC-DC converter (6 A)", "power", "dc_dc_converter", "VPT, Inc. (HEICO)", "SVPL3R306SG", (28.19, 28.19, 7.01), 21,
    {"kind": "box", "x": 28.19, "y": 28.19, "z": 7.01}, "https://components101.com/sites/default/files/2020-11/SVRPL3R306SG-Datasheet.pdf", "VPT SVPL3R306SG data sheet",
    "Low-profile 1.110 x 1.110 x 0.276 in (28.19 x 28.19 x 7.01 mm), 21 g maximum, up to 6 A (0 to 22.8 W depending on output voltage), 3.1 to 5.5 V input.",
    fields=("dimensions_mm", "mass_g", "electrical"), vendor_country="USA", mass_note="maximum per data sheet",
    electrical={"voltage_V": {"min": 3.1, "max": 5.5}, "current_A": 6, "power_W": {"peak": 22.8}})

# ---- more Analog Devices MEMS IMUs (same family as cots_2026_11_11)
for id, model, url, dims, mass, gyro_range, bias, accel_g, current_mA, temp, mass_note in (
        ("adi_adis16470", "ADIS16470", "https://wcm-cce.cldnet.analog.com/media/en/technical-documentation/data-sheets/ADIS16470.pdf", (11, 15, 11), 1.3, 2000, 8, 40, 42, (-25, 85), None),
        ("adi_adis16505", "ADIS16505", "https://www-cce.cldnet.analog.com/media/en/technical-documentation/data-sheets/adis16505.pdf", (15, 15, 5), 1.75, 2000, 2.3, 8, 44, (-40, 105), "upper bound (<1.75 g)")):
    extra = {"mass_note": mass_note} if mass_note else {}
    add(id, "Analog Devices " + model + " MEMS inertial measurement unit (BGA)", "adcs", "imu", "Analog Devices", model, dims, mass,
        {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]}, url, "Analog Devices " + model + " data sheet",
        "Approximately " + " x ".join(str(v) for v in dims) + " mm BGA, " + str(mass) + " g (Table 4), gyro up to +-" + str(gyro_range) + " deg/s, in-run bias " + str(bias) + " deg/h (best model), accelerometer +-" + str(accel_g) + " g, 3.0 to 3.6 V, " + str(current_mA) + " mA typical, SPI, " + str(temp[0]) + " to +" + str(temp[1]) + " C. Commercial part.",
        fields=("dimensions_mm", "mass_g", "adcs", "electrical", "thermal"), vendor_country="USA", distributors=["Digi-Key", "Mouser", "Analog Devices"], cost=cost(basis="distributor"),
        adcs={"gyro_range_deg_s": gyro_range, "gyro_bias_stability_deg_h": bias, "accel_range_g": accel_g}, electrical={"voltage_V": {"min": 3.0, "max": 3.6}, "current_mA": current_mA, "interfaces": ["SPI"]},
        thermal={"operating_temperature_C": {"min": temp[0], "max": temp[1]}}, **extra)

add("saft_ls14500", "Saft LS 14500 primary lithium-thionyl chloride cell (AA, 2.6 Ah)", "power", "cell", "Saft", "LS 14500", (14.65, 14.65, 50.3), 16.7,
    {"kind": "cell_18650", "diameter": 14.65, "length": 50.3}, "https://media.elv.com/file/111947_ls14500_data.pdf", "Saft LS 14500 data sheet",
    "Diameter max 14.65 mm, height max 50.3 mm, typical weight 16.7 g, 2.6 Ah nominal (2 mA, +20 C, 2.0 V cut-off), 3.6 V nominal, -60 to +85 C. Primary (non-rechargeable) cell.",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal"), vendor_country="France", distributors=["Digi-Key", "Farnell", "distributors"], cost=cost(basis="distributor"),
    electrical={"capacity_Ah": 2.6, "voltage_V": {"nominal": 3.6}, "chemistry": "Li-SOCl2 primary"}, thermal={"operating_temperature_C": {"min": -60, "max": 85}})
SAFT_SELECTOR = "https://www.master-instruments.com.au/files/battery_information/saft_lithium_product_selector_guide_54083_2_0522.pdf"
for model, capacity, diameter, height, mass in (("LS 14250", 1.2, 14.55, 25.15, 8.9), ("LS 17330", 2.1, 16.5, 33.4, 14.4), ("LS 17500", 3.6, 17.13, 50.9, 21.9), ("LS 26500", 7.7, 26.0, 50.4, 48), ("LS 33600", 17.0, 33.4, 61.6, 90)):
    add("saft_" + model.lower().replace(" ", ""), "Saft " + model + " primary lithium-thionyl chloride cell (" + str(capacity) + " Ah)", "power", "cell", "Saft", model, (diameter, diameter, height), mass,
        {"kind": "cell_18650", "diameter": diameter, "length": height}, SAFT_SELECTOR, "Saft primary lithium batteries selector guide 54083-2-0522",
        "Diameter " + str(diameter) + " mm, height " + str(height) + " mm, weight " + str(mass) + " g, " + str(capacity) + " Ah nominal, 3.6 V Li-SOCl2 bobbin cell (selector guide table).",
        fields=("dimensions_mm", "mass_g", "electrical"), vendor_country="France", distributors=["Digi-Key", "Farnell", "distributors"], cost=cost(basis="distributor"),
        electrical={"capacity_Ah": capacity, "voltage_V": {"nominal": 3.6}, "chemistry": "Li-SOCl2 primary"})

add("molicel_inr21700_p45b", "Molicel INR-21700-P45B cylindrical Li-ion cell (4500 mAh, 45 A)", "power", "cell", "E-One Moli Energy (Molicel)", "INR-21700-P45B", (21.55, 21.55, 70.15), 70.0,
    {"kind": "cell_18650", "diameter": 21.55, "length": 70.15}, "https://www.kronium.cz/uploads/p45b-datasheet.pdf", "Molicel INR-21700-P45B product data sheet",
    "Diameter 21.40 +- 0.15 mm, height 70.00 +- 0.15 mm (envelope uses the maxima), weight 70.0 g maximum, 4.5 Ah typical, 3.6 V nominal, 45 A max continuous, discharge -40 to 60 C, charge 0 to 60 C.",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal"), vendor_country="Taiwan", distributors=["distributors"], cost=cost(basis="distributor"), mass_note="maximum per data sheet",
    electrical={"capacity_Ah": 4.5, "voltage_V": {"nominal": 3.6, "max": 4.2}, "max_discharge_A": 45}, thermal={"operating_temperature_C": {"min": -40, "max": 60}})
add("lg_inr21700_m50lt", "LG INR21700 M50LT cylindrical Li-ion cell (18.2 Wh)", "power", "cell", "LG Energy Solution", "INR21700 M50LT", (21.44, 21.44, 70.65), 68.2,
    {"kind": "cell_18650", "diameter": 21.44, "length": 70.65}, "https://evwest.com/support/21700_M50LT_datasheet.pdf", "LG INR21700 M50LT product specification (preliminary)",
    "Diameter <= 21.44 mm, height <= 70.65 mm, weight with tube and washer 68.2 +- 1.0 g (marked TBD in this preliminary specification), 18.2 Wh nominal, 3.69 V average, charge 0 to 45 C, discharge -20 to 55 C.",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal"), vendor_country="South Korea", distributors=["distributors"], cost=cost(basis="distributor"), mass_note="preliminary specification value",
    electrical={"energy_Wh": 18.2, "voltage_V": {"nominal": 3.69}}, thermal={"operating_temperature_C": {"min": -20, "max": 55}})
for id, series, url, dims, mass, power, vin, models, note in (
        ("vpt_svsa2800s", "SVSA2800S", "https://cdn.craft.cloud/8b2193af-9254-40b8-94b1-f0108baf88de/assets/products/datasheets/DS-SVSA2800S-9848-14.pdf", (27.31, 27.31, 6.86), 15, 6, (15, 50), "SVSA283R3S, 2805S, 285R2S, 2807S, 2812S, 2815S", "1.075 x 1.075 x 0.270 in low-profile case, 15 g non-flanged (20 g flanged), 4 to 6 W, 15 to 50 V continuous input, 80 V transient."),
        ("vpt_svfl2800s", "SVFL2800S", "https://cdn.craft.cloud/8b2193af-9254-40b8-94b1-f0108baf88de/assets/products/datasheets/DS-SVFL2800S-9842-13.pdf", (76.33, 38.23, 10.16), 86, 120, (16, 40), "SVFL283R3S, 2805S, 286R3S, 2812S, 2815S", "3.005 x 1.505 x 0.400 in case (max), 86 g max, 66 to 120 W, 16 to 40 V continuous input, 50 V transient."),
        ("vpt_svrch2800s", "SVRCH2800S", "https://cdn.craft.cloud/8b2193af-9254-40b8-94b1-f0108baf88de/assets/products/datasheets/DS-SVRCH2800S-20287-7.pdf", (27.31, 27.31, 6.86), 16, 1.5, (16, 40), "SVRCH283R3S, 2805S, 2812S, 2815S", "1.075 x 1.075 x 0.270 in low-profile case, 16 g non-flanged (20 g flanged), 1.2 to 1.5 W, 16 to 40 V continuous input, 50 V transient.")):
    add(id, "VPT " + series + " space DC-DC converter (" + str(power) + " W max, non-flanged)", "power", "dc_dc_converter", "VPT, Inc. (HEICO)", series + " (non-flanged)", dims, mass,
        {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]}, url, "VPT " + series + " data sheet", note + " Models: " + models + ".",
        fields=("dimensions_mm", "mass_g", "electrical"), vendor_country="USA",
        electrical={"voltage_V": {"min": vin[0], "nominal": 28, "max": vin[1]}, "power_W": {"peak": power}})
for id, series, url, dims, mass, power, vin, models, note in (
        ("vpt_svrch2800d", "SVRCH2800D", "https://cdn.craft.cloud/8b2193af-9254-40b8-94b1-f0108baf88de/assets/products/datasheets/DS-SVRCH2800D-30993-6.pdf", (27.31, 27.31, 6.86), 16, 1.5, (16, 40), "SVRCH2805D, 2812D, 2815D (dual)", "1.075 x 1.075 x 0.270 in low-profile case, 16 g max non-flanged (20 g flanged), 1.5 W total, 16 to 40 V continuous input, 50 V transient."),
        ("vpt_vsc5_2800d", "VSC5-2800D", "https://cdn.craft.cloud/8b2193af-9254-40b8-94b1-f0108baf88de/assets/products/datasheets/DS-VSC5-2800D-9.docx-89821-1-1_2026-08-19-132317_snqo.pdf", (28.19, 28.19, 9.14), 24, 5, (15, 50), "VSC5-2805D, 2812D, 2815D (dual)", "1.110 x 1.110 x 0.360 in case, 24 g max, 5 W total (3.5 W per output), 15 to 50 V continuous input, 80 V transient, radiation tolerant.")):
    add(id, "VPT " + series + " space DC-DC converter (" + str(power) + " W, dual output)", "power", "dc_dc_converter", "VPT, Inc. (HEICO)", series, dims, mass,
        {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]}, url, "VPT " + series + " data sheet", note + " Models: " + models + ".",
        fields=("dimensions_mm", "mass_g", "electrical"), vendor_country="USA", mass_note="maximum per data sheet",
        electrical={"voltage_V": {"min": vin[0], "nominal": 28, "max": vin[1]}, "power_W": {"peak": power}})
add("interpoint_msa_plus", "Crane Interpoint MSA+ space DC-DC converter, 6 W (standard C4 case)", "power", "dc_dc_converter", "Crane Aerospace & Electronics (Interpoint)", "MSA+28xx (C4 case)", (27.05, 27.05, 8.89), 23,
    {"kind": "box", "x": 27.05, "y": 27.05, "z": 8.89}, "https://www.craneae.com/sites/default/files/documents/MSA%2B_DC-DC_Converters.pdf", "Crane Interpoint MSA+ series data sheet (preliminary)",
    "Hermetic C4 case 1.065 x 1.065 x 0.350 in (27.05 x 27.05 x 8.89 mm), 23 g maximum, 5 W (3.3 V) or 6 W, singles and duals, 15 to 50 V continuous input, 80 V transient. Data sheet marked preliminary.",
    fields=("dimensions_mm", "mass_g", "electrical"), vendor_country="USA", mass_note="maximum per data sheet",
    electrical={"voltage_V": {"min": 15, "nominal": 28, "max": 50}, "power_W": {"peak": 6}})
