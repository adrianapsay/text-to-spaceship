"""Parts added 2026-11-10 (evening) from satsearch marketplace listings read one page at a time with the listing URL recorded per part.
Values are the listing's specification table (vendor supplied). Only parts whose listing states outer dimensions and mass are included;
listings without dimensions (DHV EPS, 2NDSpace SOLO-EPS, Sensorpia MS-37, TakeMe2Space, ...) are left out rather than guessed.
Photos: product image URL per listing in PHOTOS (fetched by the laptop download script)."""
from parts_data._common import part, source, cost

PARTS = []
PHOTOS = {}
ACCESS = "satsearch listing read 2026-11-10"


def listing(url, title, fields, notes):
    return source("datasheet", url, "satsearch listing: " + title + " (specification table)", fields, notes=notes, date="2026-11-10")


def add(id, name, category, subcategory, vendor, model, dims, mass, shape, url, title, notes, photo, fields=("dimensions_mm", "mass_g"), **extra):
    PARTS.append(part(id, name, category, subcategory, vendor, model, dims, mass, shape, listing(url, title, list(fields), notes), distributors=["satsearch", "direct"], status="in_production", fidelity="envelope_plus_features", cost=cost(basis="quote"), **extra))
    PHOTOS[id] = photo


# ---- ADCS sensors
add("sstl_sgr_ligo", "SSTL SGR-Ligo space GNSS receiver board", "adcs", "gnss_receiver", "Surrey Satellite Technology Ltd (SSTL)", "SGR-Ligo", (92, 87, 12), 90,
    {"kind": "pc104_board", "x": 92, "y": 87, "z": 1.6, "components_height": 10.4},
    "https://satsearch.co/products/sstl-sgr-ligo-space-gnss-receiver", "SSTL SGR-Ligo", "92 x 87 x 12 mm, 90 g, <0.5 W, 3.3 V or 5 V bus, UART/CAN/I2C, -20 to 50 C, >5 krad.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_9ieza8_sstl_sgr_ligo.jpg", fields=("dimensions_mm", "mass_g", "electrical", "thermal"),
    vendor_country="United Kingdom", electrical={"power_W": {"nominal": 0.5}, "voltage_V": {"nominal": 3.3}, "interfaces": ["UART", "CAN", "I2C"]}, thermal={"operating_temperature_C": {"min": -20, "max": 50}}, environment={"radiation_krad": 5})
add("spacemanic_celeste_gnss", "Spacemanic Celeste GNSS receiver", "adcs", "gnss_receiver", "Spacemanic CZ s.r.o.", "Celeste", (67, 42, 7.5), 25,
    {"kind": "box", "x": 67, "y": 42, "z": 7.5},
    "https://satsearch.co/products/spacemanic-celeste-the-gnss-receiver", "Spacemanic Celeste GNSS receiver", "67 x 42 x 7.5 mm, 25 g, 250 mW average, 3.3 V (5 V for CAN), UART/CAN/RS485/I2C, -40 to 85 C.",
    "https://cdn.satsearch.com/product-images/image-spacemanic-cz-sro-celeste-gnss-receiver-m0370x.jpg", fields=("dimensions_mm", "mass_g", "electrical", "thermal"),
    vendor_country="Czech Republic", electrical={"power_W": {"nominal": 0.25}, "voltage_V": {"nominal": 3.3}, "interfaces": ["UART", "CAN", "RS485", "I2C"]}, thermal={"operating_temperature_C": {"min": -40, "max": 85}})
add("needronix_eagle_fss", "Needronix Eagle miniature digital dual-axis fine sun sensor", "adcs", "sun_sensor", "Needronix", "Eagle", (15, 15.5, 4.6), 3,
    {"kind": "box", "x": 15, "y": 15.5, "z": 4.6},
    "https://satsearch.co/products/needronix-nxss3v00", "Needronix Eagle fine sun sensor", "15 x 15.5 x 4.6 mm, 3 g incl. ribbon cable, 7 mW, 2.6-3.5 V, I2C, 110 x 110 deg FOV, <0.15 deg 3-sigma, -45 to 85 C.",
    "https://cdn.satsearch.com/product-images/image-needronix-eagle-5hjp09.jpg", fields=("dimensions_mm", "mass_g", "electrical", "adcs", "thermal"),
    vendor_country="Slovakia", electrical={"power_W": {"nominal": 0.007}, "voltage_V": {"min": 2.6, "max": 3.5}, "interfaces": ["I2C"]}, adcs={"fov_deg": 110, "accuracy_deg": 0.15}, thermal={"operating_temperature_C": {"min": -45, "max": 85}})
add("redwire_micro_sun_sensor", "Redwire micro sun sensor (analog, with glass)", "adcs", "sun_sensor", "Redwire Space", "Micro Sun Sensor", (23, 15.3, 6), 2,
    {"kind": "box", "x": 23, "y": 15.3, "z": 6},
    "https://satsearch.co/products/redwirespace-micro-sun-sensor", "Redwire Micro Sun Sensor", "23 x 15.3 x 6 mm, <2 g without wires, <15 mW, 3.3 or 5 V, analog 0-2.1 V output, FOV +-85 deg.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_gp5xaj_redwire_micro_sun_sensor.jpg", fields=("dimensions_mm", "mass_g", "electrical", "adcs"),
    vendor_country="USA", electrical={"power_W": {"nominal": 0.015}, "voltage_V": {"nominal": 3.3}, "interfaces": ["analog"]}, adcs={"fov_deg": 170})
add("bradford_mini_fine_sun_sensor", "Bradford Space mini fine sun sensor", "adcs", "sun_sensor", "Bradford Space", "Mini Fine Sun Sensor", (50, 46, 17), 50,
    {"kind": "box", "x": 50, "y": 46, "z": 17},
    "https://satsearch.co/products/bradford-mini-fine-sun-sensor", "Bradford Mini Fine Sun Sensor", "50 x 46 x 17 mm, 50 g, FOV 128 x 128 deg nominal (172 x 172 unobstructed), +-0.2 deg 3-sigma with look-up table; analog current outputs.",
    "https://cdn.satsearch.com/product-images/satsearch_hiztre_bradford_engineering_b_v_mini_fine_sun_sensor.jpg", fields=("dimensions_mm", "mass_g", "adcs"),
    vendor_country="Netherlands", adcs={"fov_deg": 128, "accuracy_deg": 0.2})
add("cgstl_cgudss01", "Chang Guang CGUDSS01 digital sun sensor", "adcs", "sun_sensor", "Chang Guang Satellite Technology", "CGUDSS01", (48, 36, 16.9), 50,
    {"kind": "box", "x": 48, "y": 36, "z": 16.9},
    "https://satsearch.co/products/cgsatellite-cgudss01-digital-sun-sensor", "Chang Guang CGUDSS01 digital sun sensor", "48 x 36 x 16.9 mm, 50 g, 0.15 W, 5.2 V, RS422, FOV +-60 deg, 0.5 deg precision, -30 to 60 C.",
    "https://cdn.satsearch.com/product-images/satsearch_koquap_cgsatellite_digital_sun_sensor.png", fields=("dimensions_mm", "mass_g", "electrical", "adcs", "thermal"),
    vendor_country="China", electrical={"power_W": {"nominal": 0.15}, "voltage_V": {"nominal": 5.2}, "interfaces": ["RS422"]}, adcs={"fov_deg": 120, "accuracy_deg": 0.5}, thermal={"operating_temperature_C": {"min": -30, "max": 60}})
add("arcsec_twinkle", "arcsec Twinkle miniature star tracker", "adcs", "star_tracker", "arcsec", "Twinkle", (20, 20, 40), 35,
    {"kind": "camera_box_lens", "x": 20, "y": 20, "z": 30, "lens_diameter": 14, "lens_length": 10},
    "https://satsearch.co/products/arcsec-twinkle-star-tracker", "arcsec Twinkle star tracker", "20 x 20 x 40 mm, 35 g, <1 W, 5 V, RS485, 15 arcsec cross-boresight / 90 arcsec about-boresight (1-sigma, spec table).",
    "https://cdn.satsearch.com/product-images/image-arcsec-twinkle-star-tracker-x82vtk.jpg", fields=("dimensions_mm", "mass_g", "electrical", "adcs"),
    vendor_country="Belgium", electrical={"power_W": {"nominal": 1.0}, "voltage_V": {"nominal": 5}, "interfaces": ["RS485"]}, adcs={"accuracy_arcsec_cross_boresight": 15, "accuracy_arcsec_about_boresight": 90})
add("kairospace_star_tracker", "KAIROSPACE star tracker (with baffle)", "adcs", "star_tracker", "KAIROSPACE Co., Ltd.", "Star tracker", (56, 60, 93), 197,
    {"kind": "camera_box_lens", "x": 56, "y": 60, "z": 20, "lens_diameter": 56, "lens_length": 73},
    "https://satsearch.co/products/kairospace-star-tracker", "KAIROSPACE star tracker", "56 x 60 x 93 mm, 197 g including baffle, 5 V, CAN / RS485, <5 arcsec 3-sigma, -30 to 40 C.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_vhveeq_kairo-space_star-tracker.png", fields=("dimensions_mm", "mass_g", "electrical", "adcs", "thermal"),
    vendor_country="South Korea", electrical={"voltage_V": {"nominal": 5}, "interfaces": ["CAN", "RS485"]}, adcs={"accuracy_arcsec": 5}, thermal={"operating_temperature_C": {"min": -30, "max": 40}})
add("solarmems_nanost_cubesat", "Solar MEMS nanoST star tracker (CubeSat version)", "adcs", "star_tracker", "Solar MEMS Technologies S.L.", "nanoST (CubeSat)", (52, 38, 90), 180,
    {"kind": "camera_box_lens", "x": 52, "y": 38, "z": 60, "lens_diameter": 30, "lens_length": 30},
    "https://satsearch.co/products/solarmems-stns-star-tracker-for-small-satellites", "Solar MEMS nanoST star tracker", "CubeSat version 90 x 52 x 38 mm, 180 g (non-CubeSat 118 x 63 x 63 mm, 220 g), 1 W, 5 V, UART, -30 to 70 C.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_56wcj6_solarmems_stns-star-tracker-for-small-satellites.jpg", fields=("dimensions_mm", "mass_g", "electrical", "thermal"),
    vendor_country="Spain", electrical={"power_W": {"nominal": 1.0}, "voltage_V": {"nominal": 5}, "interfaces": ["UART"]}, thermal={"operating_temperature_C": {"min": -30, "max": 70}})
add("bst_st200", "Berlin Space Technologies ST200 star tracker (no baffle)", "adcs", "star_tracker", "Berlin Space Technologies", "ST200", (30, 30, 39), 40,
    {"kind": "camera_box_lens", "x": 30, "y": 30, "z": 29, "lens_diameter": 20, "lens_length": 10},
    "https://satsearch.co/products/berlin-space-tech-st200", "BST ST200 star tracker", "30 x 30 x 39 mm, 40 g (UART version), 0.55-0.67 W at 3.7 V, 3.7-5 V, UART, 10 arcsec pitch/yaw, 70 arcsec roll (1-sigma), -20 to 40 C.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_k4cpcs_berlin-space-tech_st200.png", fields=("dimensions_mm", "mass_g", "electrical", "adcs", "thermal"),
    vendor_country="Germany", electrical={"power_W": {"nominal": 0.6}, "voltage_V": {"min": 3.7, "max": 5}, "interfaces": ["UART"]}, adcs={"accuracy_arcsec_cross_boresight": 10, "accuracy_arcsec_about_boresight": 70}, thermal={"operating_temperature_C": {"min": -20, "max": 40}})
add("bst_st200_baffle", "Berlin Space Technologies ST200 star tracker with 40 deg sun-exclusion baffle", "adcs", "star_tracker", "Berlin Space Technologies", "ST200 + baffle", (50, 50, 83), 106,
    {"kind": "camera_box_lens", "x": 30, "y": 30, "z": 30, "lens_diameter": 20, "lens_length": 53, "baffle_diameter": 50},
    "https://satsearch.co/products/berlin-space-tech-st200", "BST ST200 star tracker", "With baffle 50 x 50 x 83 mm, 106 g; same electronics as the ST200.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_k4cpcs_berlin-space-tech_st200.png", fields=("dimensions_mm", "mass_g"),
    vendor_country="Germany", electrical={"power_W": {"nominal": 0.6}, "voltage_V": {"min": 3.7, "max": 5}, "interfaces": ["UART"]})
add("bartington_spacemag_lite", "Bartington Spacemag-Lite three-axis magnetometer probe", "adcs", "magnetometer", "Bartington Instruments", "Spacemag-Lite", (20, 20, 20), 42,
    {"kind": "box", "x": 20, "y": 20, "z": 20},
    "https://satsearch.co/products/bartington-instruments-spacemag-lite-three-axis-magnetometer", "Bartington Spacemag-Lite", "Probe 20 x 20 x 20 mm, 42 g probe (67 g unit, 94 g with harness), 5 V or 3.3 V, +-60 uT, analog +-3 V differential outputs, -40 to 65 C continuous. 2 m harness not modelled.",
    "https://cdn.satsearch.com/product-images/image-bartington-instruments-spacemag-lite-three-axis-magnetometer-dw9777.jpg", fields=("dimensions_mm", "mass_g", "electrical", "thermal"),
    vendor_country="United Kingdom", electrical={"voltage_V": {"nominal": 5}, "interfaces": ["analog differential"]}, thermal={"operating_temperature_C": {"min": -40, "max": 65}})
add("cgstl_cgumm01", "Chang Guang CGUMM01 magnetometer (cylindrical)", "adcs", "magnetometer", "Chang Guang Satellite Technology", "CGUMM01", (98, 98, 80), 195,
    {"kind": "cylinder", "diameter": 98, "length": 80},
    "https://satsearch.co/products/cgsatellite-cgumm01-magnetometer", "Chang Guang CGUMM01 magnetometer", "Diameter 98 mm, length 80 mm, 195 g, 0.54 W, 12 V, RS422, 10 Hz.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_y3uoip_cgstl_cgumm01.jpeg", fields=("dimensions_mm", "mass_g", "electrical"),
    vendor_country="China", electrical={"power_W": {"nominal": 0.54}, "voltage_V": {"nominal": 12}, "interfaces": ["RS422"]})
add("lusospace_mag28", "Lusospace MAG28 analogue magnetometer", "adcs", "magnetometer", "Lusospace", "MAG28", (85, 60, 53), 300,
    {"kind": "box", "x": 85, "y": 60, "z": 53},
    "https://satsearch.co/products/lusospace-mag28-analogue-magnetometer", "Lusospace MAG28", "85 x 60 x 53 mm, 300 g, <1 W, 15-40 V, +-70000 nT, linearity <0.2 percent, -30 to 60 C.",
    "https://cdn.satsearch.com/product-images/image-lusospace-mag28-analogue-magnetometer-vgy415.jpg", fields=("dimensions_mm", "mass_g", "electrical", "thermal"),
    vendor_country="Portugal", electrical={"power_W": {"nominal": 1.0}, "voltage_V": {"min": 15, "max": 40}, "interfaces": ["analog"]}, thermal={"operating_temperature_C": {"min": -30, "max": 60}})

# ---- Comms
add("needronix_cormorant", "Needronix Cormorant VHF/UHF CubeSat transceiver", "comms", "transceiver", "Needronix", "Cormorant", (70, 40, 6.5), 22,
    {"kind": "box", "x": 70, "y": 40, "z": 6.5},
    "https://satsearch.co/products/needronix-cormorant", "Needronix Cormorant transceiver", "70 x 40 x 6.5 mm, 22 g, 3.3 V, RS485/UART/I2C, 430-440 MHz or 144-146 MHz, max 30 dBm, -45 to 85 C.",
    "https://cdn.satsearch.com/product-images/image-needronix-cormorant-6yr53l.jpg", fields=("dimensions_mm", "mass_g", "electrical", "rf", "thermal"),
    vendor_country="Slovakia", electrical={"voltage_V": {"nominal": 3.3}, "interfaces": ["RS485", "UART", "I2C"]}, rf={"band": "UHF/VHF", "frequency_MHz": [[430, 440], [144, 146]], "output_power_dBm": 30}, thermal={"operating_temperature_C": {"min": -45, "max": 85}})
add("spacemanic_murgas", "Spacemanic Murgas UHF/VHF transceiver", "comms", "transceiver", "Spacemanic CZ s.r.o.", "Murgas", (67, 42, 7.5), 25,
    {"kind": "box", "x": 67, "y": 42, "z": 7.5},
    "https://satsearch.co/products/spacemanic-murgas-the-uhf-vhf-transceiver", "Spacemanic Murgas transceiver", "67 x 42 x 7.5 mm, 25 g, 3.3 W transmitting / 0.14 W receiving, 3.3 V (5 V CAN), UART/CAN/RS485/I2C, 144-146 / 430-440 / 400-402 MHz, -40 to 85 C.",
    "https://cdn.satsearch.com/product-images/image-spacemanic-cz-sro-murgas-uhfvhf-transceiver-mx5vs0.jpg", fields=("dimensions_mm", "mass_g", "electrical", "rf", "thermal"),
    vendor_country="Czech Republic", electrical={"power_W": {"peak": 3.3, "idle": 0.14}, "voltage_V": {"nominal": 3.3}, "interfaces": ["UART", "CAN", "RS485", "I2C"]}, rf={"band": "UHF/VHF", "frequency_MHz": [[144, 146], [430, 440], [400, 402]]}, thermal={"operating_temperature_C": {"min": -40, "max": 85}})
add("aac_pulsar_vutrx", "AAC Clyde Space PULSAR-VUTRX VHF uplink / UHF downlink transceiver", "comms", "transceiver", "AAC Clyde Space", "PULSAR-VUTRX", (96, 90, 16.51), 100,
    {"kind": "pc104_board", "x": 96, "y": 90, "z": 1.6, "components_height": 14.91},
    "https://satsearch.co/products/aac-clyde-pulsar-vutrx-vhf-uhf-transceiver", "AAC Clyde Space PULSAR-VUTRX", "96 x 90 x 16.51 mm, <100 g, I2C, VHF uplink / UHF downlink, 27-33 dBm, -25 to 60 C.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_w21yt4_aac_clyde_space_pulsar_utrx_uhf.jpg", fields=("dimensions_mm", "mass_g", "rf", "thermal"),
    vendor_country="Sweden / UK", electrical={"interfaces": ["I2C", "PC/104 stack"]}, rf={"band": "VHF/UHF", "output_power_dBm": 33}, thermal={"operating_temperature_C": {"min": -25, "max": 60}})
add("trad_hircom", "TRAD HIRCOM CubeSat UHF transceiver (PC/104)", "comms", "transceiver", "TRAD Tests & Radiations", "HIRCOM", (95, 90, 20), 85,
    {"kind": "pc104_board", "x": 95, "y": 90, "z": 1.6, "components_height": 18.4},
    "https://satsearch.co/products/trad-tests-and-radiations-hircom-cubesat-uhf-transceiver", "TRAD HIRCOM UHF transceiver", "90 x 95 x 20 mm, 85 g, 4.8 W transmit / 0.63 W receive, 5 V PA and 3.3 V, 400-438 MHz, 2 W (33 dBm), -35 to 80 C.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_sc4kdx_trad_hircom.jpg", fields=("dimensions_mm", "mass_g", "electrical", "rf", "thermal"),
    vendor_country="France", electrical={"power_W": {"peak": 4.8, "nominal": 0.63}, "voltage_V": {"nominal": 5}, "interfaces": ["PC/104 stack"]}, rf={"band": "UHF", "frequency_MHz": [400, 438], "output_power_dBm": 33}, thermal={"operating_temperature_C": {"min": -35, "max": 80}})
add("cubecom_xant", "CUBECOM XANT X-band patch antenna", "comms", "antenna", "CUBECOM", "XANT", (51, 51, 5), 26.5,
    {"kind": "patch_antenna", "x": 51, "y": 51, "z": 4, "patch_inset": 8, "patch_height": 1},
    "https://satsearch.co/products/cubecom-xant-x-band-patch-antenna", "CUBECOM XANT X-band patch antenna", "51 x 51 x 5 mm, 26.5 g, 8-8.4 GHz, 8 dBi max, RHCP or LHCP, single SMP connector.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_u92fk1_cubecom_xant-x-band-patch-antenna.jpg", fields=("dimensions_mm", "mass_g", "rf"),
    vendor_country="South Africa", rf={"band": "X", "frequency_MHz": [8000, 8400], "gain_dBi": 8, "polarization": "circular (RHCP or LHCP)"}, rf_connectors=["SMP"])
add("iq_spacecom_sband_patch_single", "IQ spacecom S-band single patch antenna", "comms", "antenna", "IQ spacecom", "S-Band Antenna (single patch)", (70, 70, 3.4), 49,
    {"kind": "patch_antenna", "x": 70, "y": 70, "z": 2.6, "patch_inset": 10, "patch_height": 0.8},
    "https://satsearch.co/products/iq-s-band-antenna", "IQ spacecom S-band antennas", "Single patch 70 x 70 x 3.4 mm, 49 g; 1.98-2.5 GHz, circular polarization, SMA female or UMP.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_qrcf2d_iq_s-band-antenna.jpg", fields=("dimensions_mm", "mass_g", "rf"),
    vendor_country="Germany", rf={"band": "S", "frequency_MHz": [1980, 2500], "polarization": "circular"}, rf_connectors=["SMA female or UMP"])
add("iq_spacecom_sband_patch_dual", "IQ spacecom S-band dual patch antenna", "comms", "antenna", "IQ spacecom", "S-Band Antenna (dual patch)", (80, 100, 3.4), 62,
    {"kind": "patch_antenna", "x": 80, "y": 100, "z": 2.6, "patch_inset": 10, "patch_height": 0.8},
    "https://satsearch.co/products/iq-s-band-antenna", "IQ spacecom S-band antennas", "Dual patch 80 x 100 x 3.4 mm, 62 g; 1.98-2.5 GHz, circular polarization, SMA female or UMP.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_qrcf2d_iq_s-band-antenna.jpg", fields=("dimensions_mm", "mass_g", "rf"),
    vendor_country="Germany", rf={"band": "S", "frequency_MHz": [1980, 2500], "polarization": "circular"}, rf_connectors=["SMA female or UMP"])

# ---- Power
add("npc_spacemind_gemini_eps", "NPC SPACEMIND GEMINI CubeSat EPS (PC/104)", "power", "eps", "NPC SPACEMIND", "GEMINI", (95.9, 90.2, 25), 300,
    {"kind": "pc104_board", "x": 95.9, "y": 90.2, "z": 1.6, "components_height": 23.4},
    "https://satsearch.co/products/npcspacemind-gemini-cubesat-eps", "NPC SPACEMIND GEMINI EPS", "90.2 x 95.9 x 25 mm, 300 g, 6 input channels 5-20 V, programmable outputs 3.3 / 5 / 6-12 / 24 V, 84 Wh per 8-cell pack (packs separate).",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_g7vace_npc_spacemind_eps.jpg", fields=("dimensions_mm", "mass_g", "electrical"),
    vendor_country="Italy", electrical={"voltage_V": {"nominal": 5}, "interfaces": ["PC/104 stack"]})
# (EXA 25 Whr array removed 2026-11-11: it is the same product as exa_ba01_s in power.py, now verified from the EXA datasheet.)

# ---- Avionics
add("steel_electronique_mobc", "STEEL Electronique MOBC on-board computer for nanosatellites (Zynq 7030)", "avionics", "obc", "STEEL Electronique", "MOBC", (99.4, 90.2, 34.4), 286,
    {"kind": "pc104_board", "x": 99.4, "y": 90.2, "z": 1.6, "components_height": 32.8},
    "https://satsearch.co/products/steel-electronique-mobc-on-board-computer-for-nanosatellites", "STEEL Electronique MOBC", "90.2 x 99.4 x 34.4 mm, 286 g with heatsink frame, 3.5 W typical, 5 V, Zynq 7030, SpaceWire x2, RS485/RS422, CAN, I2C, SPI, -30 to 55 C.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_swqcil_steel-electronique_mobc-on-board-computer-for-nanosatellites.jpg", fields=("dimensions_mm", "mass_g", "electrical", "thermal"),
    vendor_country="France", electrical={"power_W": {"nominal": 3.5}, "voltage_V": {"nominal": 5}, "interfaces": ["SpaceWire", "RS485/RS422", "CAN", "I2C", "SPI", "PC/104 backplane"]}, thermal={"operating_temperature_C": {"min": -30, "max": 55}})

# ---- Propulsion
add("thrustme_npt30_i2", "ThrustMe NPT30-I2 1U iodine electric propulsion system", "propulsion", "electric_thruster", "ThrustMe", "NPT30-I2 1U", (96, 96, 113), 1200,
    {"kind": "electric_thruster", "x": 96, "y": 96, "z": 103, "emitter_diameter": 40, "emitter_length": 10},
    "https://satsearch.co/products/thrustme-npt30-i2-1u-electric-propulsion-system", "ThrustMe NPT30-I2 1U", "96 x 96 x 113 mm, 1.2 kg wet, 35-65 W, 12-28 V, 0.3-1.1 mN, Isp <2400 s, total impulse <5500 Ns, solid iodine, I2C/CAN.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_3qqgge_thrustme_npt30-i2_1u.jpg", fields=("dimensions_mm", "mass_g", "electrical", "propulsion"),
    vendor_country="France", electrical={"power_W": {"min": 35, "max": 65}, "voltage_V": {"min": 12, "max": 28}, "interfaces": ["I2C", "CAN"]}, propulsion={"thrust_mN": [0.3, 1.1], "isp_s": 2400, "total_impulse_Ns": 5500, "propellant": "iodine"})
add("steamjet_steam_thruster_one", "SteamJet Steam Thruster One 2U water resistojet propulsion unit", "propulsion", "resistojet", "SteamJet Space Systems", "Steam Thruster One (2U)", (208, 102, 121), 1700,
    {"kind": "thruster_box_nozzle", "x": 208, "y": 102, "z": 105, "nozzle_diameter": 14, "nozzle_length": 16, "tank_diameter": 90},
    "https://satsearch.co/products/steamjet-space-steam-thruster-one", "SteamJet Steam Thruster One", "208 x 102 x 121 mm, 1.7 kg wet (700 g water), <19.9 W thrusting, 17-33 V, 5-20 mN, Isp 172 s, 1200 Ns, RS422 / UART.",
    "https://cdn.satsearch.com/product-images/image-steamjet-space-systems-steam-thruster-one-0ffz93.jpg", fields=("dimensions_mm", "mass_g", "electrical", "propulsion"),
    vendor_country="Italy", electrical={"power_W": {"peak": 19.9, "idle": 0.12}, "voltage_V": {"min": 17, "max": 33}, "interfaces": ["RS422", "UART"]}, propulsion={"thrust_mN": [5, 20], "isp_s": 172, "total_impulse_Ns": 1200, "propellant": "water"})

# ---- Payload
add("simera_triscape200", "Simera Sense TriScape200 imager (1.5 m GSD at 500 km)", "payload", "imager", "Simera Sense", "TriScape200", (216, 216, 304), 12100,
    {"kind": "camera_box_lens", "x": 216, "y": 216, "z": 224, "lens_diameter": 150, "lens_length": 80},
    "https://satsearch.co/products/simera-sense-triscape200", "Simera Sense TriScape200", "216 x 216 x 304 mm, 12.1 kg, 2.5 W idle / 5.8 W imaging, 5 V, 1.5 m GSD at 500 km, I2C/SPI (SpaceWire, RS422, RS485, CAN optional), -10 to 50 C.",
    None, fields=("dimensions_mm", "mass_g", "electrical", "thermal"),
    vendor_country="South Africa", electrical={"power_W": {"idle": 2.5, "peak": 5.8}, "voltage_V": {"nominal": 5}, "interfaces": ["I2C", "SPI", "SpaceWire (optional)", "RS422 (optional)", "CAN (optional)"]}, thermal={"operating_temperature_C": {"min": -10, "max": 50}}, payload={"gsd_m": 1.5})
add("scanway_sop_1u_65", "Scanway SOP 1U/65 optical payload (65 mm aperture)", "payload", "imager", "Scanway S.A.", "SOP 1U/65", (96, 119, 90), 800,
    {"kind": "camera_box_lens", "x": 96, "y": 119, "z": 70, "lens_diameter": 65, "lens_length": 20},
    "https://satsearch.co/products/scanway-sop-1u-65", "Scanway SOP 1U/65", "96 x 119 x 90 mm, 800 g, 65 mm aperture, 14 m GSD (spec table), LVDS/I2C/SPI.",
    "https://cdn.satsearch.com/product-images/image-scanway-sa-sop-1u65-iocmyk.jpg", fields=("dimensions_mm", "mass_g", "payload"),
    vendor_country="Poland", electrical={"interfaces": ["LVDS", "I2C", "SPI"]}, payload={"aperture_mm": 65, "gsd_m": 14})
add("xcam_c3d", "XCAM C3D CubeSat camera board with wide-field imager", "payload", "camera", "XCAM", "C3D", (95, 91, 27), 85,
    {"kind": "pc104_board", "x": 95, "y": 91, "z": 1.6, "components_height": 25.4},
    "https://satsearch.co/products/xcam-c3d-cubesat-camera", "XCAM C3D CubeSat camera", "95 x 91 x 27 mm, 85 g board + 1 WFI, 845 mW peak, I2C/SPI, 360 m GSD at 650 km with the wide-field optics, -25 to 65 C.",
    "https://cdn.satsearch.com/product-images/satsearch_product-image_pozfjo_xcam_c3d.jpg", fields=("dimensions_mm", "mass_g", "electrical", "thermal"),
    vendor_country="United Kingdom", electrical={"power_W": {"peak": 0.845}, "interfaces": ["I2C", "SPI"]}, thermal={"operating_temperature_C": {"min": -25, "max": 65}})
add("crystalspace_micro_camera", "Crystalspace micro camera system (5 MP)", "payload", "camera", "Crystalspace", "Micro Camera System", (45, 25, 45), 50,
    {"kind": "camera_box_lens", "x": 45, "y": 25, "z": 35, "lens_diameter": 15, "lens_length": 10},
    "https://satsearch.co/products/crystalspace-micro-camera-system", "Crystalspace Micro Camera System", "45 x 25 x 45 mm, <50 g, 240 mW peak / 75 mW nominal, 5 MP sensor, -30 to 75 C.",
    "https://cdn.satsearch.com/product-images/satsearch_29hy5k_crystalspace_crystal_space_micro_camera_system.jpg", fields=("dimensions_mm", "mass_g", "electrical", "thermal"),
    vendor_country="Estonia", electrical={"power_W": {"peak": 0.24, "nominal": 0.075}}, thermal={"operating_temperature_C": {"min": -30, "max": 75}})
