"""Parts added 2026-11-11 from vendor datasheets found by web search and read one PDF at a time (URL recorded per part).
Only datasheets that state outer dimensions and mass are used. Where the datasheet gives an upper bound ("<500 g") the bound is recorded and
mass_note says so. Where a stated size excludes a protrusion (a connector), the record says which one in "protrusions"."""
from parts_data._common import part, source, cost

PARTS = []


def add(id, name, category, subcategory, vendor, model, dims, mass, shape, url, title, notes, fields=("dimensions_mm", "mass_g"), **extra):
    extra.setdefault("status", "in_production")
    extra.setdefault("fidelity", "envelope_plus_features")
    extra.setdefault("distributors", ["direct"])
    extra.setdefault("cost", cost(basis="quote"))
    PARTS.append(part(id, name, category, subcategory, vendor, model, dims, mass, shape, source("datasheet", url, title, list(fields), notes=notes, date="2026-11-11"), **extra))


# ---- Spacemanic (Slovakia / Czech Republic) data sheets
add("spacemanic_eddie_obc", "Spacemanic Eddie OBC (MSP430 on-board computer module)", "avionics", "obc", "Spacemanic CZ s.r.o.", "Eddie OBC v4a", (67, 42, 7.5), 25,
    {"kind": "pc104_board", "x": 67, "y": 42, "z": 1.6, "components_height": 5.9, "hole_diameter": 2.2},
    "https://spacemanic.com/wp-content/uploads/2026/09/SM-EDI-DS-0002_3.2_Data-Sheet.pdf", "Spacemanic Eddie OBC data sheet SM-EDI-DS-0002 3.2",
    "67 x 42 x 7.5 mm, 25 g, 60 mW average / 100 mW peak, 3.3 V (5 V for CAN), CSP over I2C / RS485 / CAN, UART debug, -40 to +85 C.", fields=("dimensions_mm", "mass_g", "electrical", "thermal"),
    vendor_country="Czech Republic", electrical={"voltage_V": {"nominal": 3.3}, "power_W": {"nominal": 0.06, "peak": 0.1}, "interfaces": ["CSP I2C", "CSP RS485", "CSP CAN", "UART", "SPI", "ADC", "PWM", "GPIO"]}, thermal={"operating_temperature_C": {"min": -40, "max": 85}}, compute={"processor": "TI MSP430"})
add("spacemanic_deep_thought_obc", "Spacemanic Deep Thought OBC (on-board computer module)", "avionics", "obc", "Spacemanic CZ s.r.o.", "Deep Thought OBC", (67, 42, 7), 25,
    {"kind": "pc104_board", "x": 67, "y": 42, "z": 1.6, "components_height": 5.4, "hole_diameter": 2.2},
    "https://spacemanic.com/wp-content/uploads/2026/09/SM-DT-DS-0002_3.2_Data-Sheet.pdf", "Spacemanic Deep Thought OBC data sheet SM-DT-DS-0002 3.2",
    "67 x 42 x 7 mm, 25 g, 330 mW average / <500 mW peak, 3.0 to 3.6 V, CSP over I2C / RS485 / CAN, QSPI and SPI memory, -40 to +85 C.", fields=("dimensions_mm", "mass_g", "electrical", "thermal"),
    vendor_country="Czech Republic", electrical={"voltage_V": {"min": 3.0, "nominal": 3.3, "max": 3.6}, "power_W": {"nominal": 0.33, "peak": 0.5}, "interfaces": ["CSP I2C", "CSP RS485", "CSP CAN", "UART", "SPI", "QSPI", "ADC", "PWM", "GPIO"]}, thermal={"operating_temperature_C": {"min": -40, "max": 85}}, compute={"processor": "Microchip SAMV71 (per satnow listing)"})
add("spacemanic_amun_1u_psu", "Spacemanic AMUN 1U power supply unit with 24 Wh battery (PC/104)", "power", "eps", "Spacemanic CZ s.r.o.", "AMUN 1U PSU", (90.2, 95.9, 19.7), 185,
    {"kind": "pc104_board", "x": 95.9, "y": 90.2, "z": 1.6, "components_height": 18.1},
    "https://spacemanic.com/wp-content/uploads/2026/03/SM-AMU-DS-0001_5.2_Datasheet-AMUN-1U.pdf", "Spacemanic AMUN 1U data sheet SM-AMU-DS-0001 5.2",
    "90.2 x 95.9 x 19.7 mm, 185 g, 24 Wh 2S1P NCR18650B pack (7.2 V typical, 8.2 V max), MPPT solar input 5 V at 500 mA, outputs VBAT, 3.3 V, 5 V and 4 configurable 3.3/5 V (4 A per output, 6 A combined), CSP over I2C / RS485 / CAN, RBF and two deployment switch inputs, -40 to +85 C. The AMUN Compact sheet (5.3) states the same size and mass.",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal"), vendor_country="Czech Republic",
    electrical={"battery_energy_Wh": 24, "voltage_V": {"nominal": 7.2, "max": 8.2}, "outputs": ["VBAT", "3.3 V", "5 V", "4 x 3.3/5 V"], "interfaces": ["CSP I2C", "CSP RS485", "CSP CAN", "UART", "PC/104"]}, thermal={"operating_temperature_C": {"min": -40, "max": 85}})
add("spacemanic_sam_s", "Spacemanic SAM S deployable VHF/UHF antenna module (1U face)", "comms", "antenna", "Spacemanic CZ s.r.o.", "SAM S", (98, 98, 10.1), 55,
    {"kind": "box", "x": 98, "y": 98, "z": 10.1},
    "https://spacemanic.com/wp-content/uploads/2026/09/SM-SAM-DS-0016_4.2_SAM-S-Datasheet.pdf", "Spacemanic SAM S data sheet SM-SAM-DS-0016 4.2",
    "98 x 98 x 6.2 mm plate, 98 x 98 x 10.1 mm including components, about 55 g, VHF dipole 133-150 MHz (~2.3 dBi), UHF dipole or turnstile 380-450 MHz (~2.6 dBi), Molex PicoBlade main connector, MMCX radio connectors, -40 to +85 C. Stowed envelope; deployed elements not modelled.",
    fields=("dimensions_mm", "mass_g", "rf", "thermal"), vendor_country="Czech Republic", mass_note="approximate (~55 g) per datasheet",
    rf={"band": "VHF/UHF", "frequency_MHz": [[133, 150], [380, 450]], "gain_dBi": 2.6, "antenna_type": "deployable dipole / turnstile"}, thermal={"operating_temperature_C": {"min": -40, "max": 85}})

# ---- NewSpace Systems (South Africa) data sheets 2020
add("nss_ncss_sa05", "NewSpace Systems NCSS-SA05 analogue PSD sun sensor", "adcs", "sun_sensor", "NewSpace Systems", "NCSS-SA05", (33, 11, 6), 5,
    {"kind": "box", "x": 33, "y": 11, "z": 6},
    "https://www.cubesatshop.com/wp-content/uploads/2020/11/NewSpace-Sun-Sensor_2020-10a.pdf", "NewSpace Systems sun sensor data sheet 2020-10a",
    "33 x 11 x 6 mm, <5 g, <0.01 deg RMS over the FOV, 114 deg FOV, 5 analogue channels, 5 V, <10 mA, -25 to +70 C. Mass is the stated upper bound.",
    fields=("dimensions_mm", "mass_g", "adcs", "electrical", "thermal"), vendor_country="South Africa", mass_note="upper bound (<5 g) per datasheet", distributors=["direct", "CubeSatShop"],
    adcs={"fov_deg": 114, "accuracy_deg": 0.01}, electrical={"voltage_V": {"nominal": 5.0}, "current_mA": 10, "interfaces": ["analogue (5 channels)"]}, thermal={"operating_temperature_C": {"min": -25, "max": 70}})
add("nss_ngps_01_422", "NewSpace Systems NGPS-01-422 GPS receiver (28 V, microsatellite)", "adcs", "gnss_receiver", "NewSpace Systems", "NGPS-01-422", (155, 76, 34), 500,
    {"kind": "box", "x": 155, "y": 76, "z": 34},
    "https://www.cubesatshop.com/wp-content/uploads/2020/11/NewSpace-GPS-Receiver_2020-10a.pdf", "NewSpace Systems GPS receiver data sheet 2020-10a",
    "155 x 76 x 34 mm excluding connectors, <500 g, 1.5 W excluding the active antenna, 24-36 V unregulated isolated, RS-422 UART, 9-pin D-sub power, 26-pin HD D-sub data, SMA antenna port, -10 to +50 C acceptance. Mass is the stated upper bound.",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal"), vendor_country="South Africa", mass_note="upper bound (<500 g) per datasheet", distributors=["direct", "CubeSatShop"], satellite_class="smallsat",
    protrusions="D-sub (9-pin and 26-pin HD) and SMA connectors are outside the stated 155 x 76 x 34 mm",
    electrical={"voltage_V": {"min": 24, "max": 36}, "power_W": {"nominal": 1.5}, "interfaces": ["RS-422 UART"]}, thermal={"operating_temperature_C": {"min": -10, "max": 50}})

# ---- AAC Clyde Space data sheets
add("aac_pulsar_xant_plus", "AAC Clyde Space PULSAR-XANT-PLUS X-band patch antenna", "comms", "antenna", "AAC Clyde Space", "PULSAR-XANT-PLUS", (43, 43, 1.65), 8,
    {"kind": "patch_antenna", "x": 43, "y": 43, "z": 1.15, "patch_inset": 6, "patch_height": 0.5},
    "https://www.aac-clyde.space/wp-content/uploads/2021/10/aac-clyde-space-pulsar-xant-plus-antenna-datasheet.pdf", "AAC Clyde Space PULSAR-XANT-PLUS data sheet",
    "43 x 43 mm, 1.65 mm high excluding the connector, 8 g, 12 +- 0.5 dBi, 8.025-8.40 GHz, straight SMP connector, -40 to +85 C.", fields=("dimensions_mm", "mass_g", "rf", "thermal"),
    vendor_country="Sweden / UK", protrusions="straight SMP connector below the 1.65 mm height", rf={"band": "X", "frequency_MHz": [[8025, 8400]], "gain_dBi": 12, "antenna_type": "patch"}, thermal={"operating_temperature_C": {"min": -40, "max": 85}})
add("aac_quasar_wsant", "AAC Clyde Space QUASAR-WSANT wide-band dual-polarisation S-band antenna", "comms", "antenna", "AAC Clyde Space", "QUASAR-WSANT", (83, 83, 7), 68.5,
    {"kind": "patch_antenna", "x": 83, "y": 83, "z": 6, "patch_inset": 12, "patch_height": 1.0},
    "https://www.aac-clyde.space/wp-content/uploads/2025/09/QUASAR-WSANT-Datasheet.pdf", "AAC Clyde Space QUASAR-WSANT data sheet (2025)",
    "83 x 83 x 7 mm, 68.5 g, >5 dBic, 2025-2290 MHz, dual port dual polarisation, 2 x SMP female, -20 to +60 C operating.", fields=("dimensions_mm", "mass_g", "rf", "thermal"),
    vendor_country="Sweden / UK", rf={"band": "S", "frequency_MHz": [[2025, 2290]], "gain_dBi": 5, "polarization": "dual", "antenna_type": "patch"}, thermal={"operating_temperature_C": {"min": -20, "max": 60}})
add("aac_pm200", "AAC Clyde Space PM200 bipropellant propulsion module (with Dawn Aerospace)", "propulsion", "propulsion_module", "AAC Clyde Space", "PM200", (97.7, 95.4, 95.4), 1100,
    {"kind": "thruster_box_nozzle", "x": 97.7, "y": 95.4, "z": 85.4, "nozzle_diameter": 14, "nozzle_length": 10},
    "https://www.aac-clyde.space/wp-content/uploads/2021/11/PM200-1.pdf", "AAC Clyde Space PM200 data sheet",
    "Outer 97.7 x 95.4 x 95.4 mm, 1100 g dry, 310 g propellant, <12 W firing, <0.1 W sleep, 5 and 12 V, I2C or RS422/RS485, -5 to +35 C operating. Nozzle split of the CAD is schematic.",
    fields=("dimensions_mm", "mass_g", "propulsion", "electrical", "thermal"), vendor_country="Sweden / UK", mass_note="dry mass",
    propulsion={"type": "bipropellant (N2O / propene, Dawn Aerospace)", "propellant_mass_g": 310}, electrical={"voltage_V": {"nominal": 12}, "power_W": {"peak": 12, "idle": 0.1}, "interfaces": ["I2C", "RS422/RS485"]}, thermal={"operating_temperature_C": {"min": -5, "max": 35}})

# ---- ISISPACE antennas
add("isis_gnss_patch_gapa", "ISISPACE GNSS active patch antenna (GPS L1 / Galileo E1)", "adcs", "gnss_antenna", "ISISPACE", "GNSS Active Patch Antenna (GAPA)", (70, 70, 15), 18,
    {"kind": "patch_antenna", "x": 70, "y": 70, "z": 13, "patch_inset": 15, "patch_height": 2.0},
    "https://www.isispace.nl/wp-content/uploads/2022/09/ISIS-GAPA-DSH-0001-GNSS_Antenna_Datasheet-02_1.pdf", "ISIS GNSS Antenna data sheet ISIS-GAPA-DSH-0001 issue 2.1",
    "70 x 70 x 15 mm, 18 g, 5.2 dBi peak at 1575 MHz, 34.5 dB LNA gain, 1572-1578 MHz, 3-5 V, <10 mA at 5 V, single straight MMCX for RF and power, -30 to +70 C.", fields=("dimensions_mm", "mass_g", "rf", "electrical", "thermal"),
    vendor_country="Netherlands", rf={"band": "L1/E1", "frequency_MHz": [[1572, 1578]], "gain_dBi": 5.2, "antenna_type": "active patch"}, electrical={"voltage_V": {"min": 3, "max": 5}, "current_mA": 10}, thermal={"operating_temperature_C": {"min": -30, "max": 70}})
add("isis_sband_patch_sspa", "ISISPACE S-band patch antenna (RHCP, 2200-2290 MHz)", "comms", "antenna", "ISISPACE", "S-Band Patch Antenna", (80, 80, 8.8), 50,
    {"kind": "cylinder", "diameter": 80, "length": 8.8, "axis": "z"},
    "https://www.isispace.nl/wp-content/uploads/2021/01/ISIS-SSPA-DSH-0001-S_Patch_Antenna_Datasheet-02_00.pdf", "ISIS S-band Patch Antenna data sheet ISIS-SSPA-DSH-0001 2.0",
    "80 mm diameter, 5.0 mm high without connector, 8.8 mm with the straight SMA (envelope uses 8.8 mm), <50 g, 6.5 dBic, 2200-2290 MHz RHCP, -20 to +50 C. Mass is the stated upper bound.",
    fields=("dimensions_mm", "mass_g", "rf", "thermal"), vendor_country="Netherlands", mass_note="upper bound (<50 g) per datasheet",
    rf={"band": "S", "frequency_MHz": [[2200, 2290]], "gain_dBi": 6.5, "polarization": "RHCP", "antenna_type": "patch"}, thermal={"operating_temperature_C": {"min": -20, "max": 50}})

add("aac_pulsar_stx", "AAC Clyde Space PULSAR-STX / STXC S-band transmitter (PC/104)", "comms", "transmitter", "AAC Clyde Space", "PULSAR-STX", (96, 90, 16.9), 100,
    {"kind": "pc104_board", "x": 96, "y": 90, "z": 1.6, "components_height": 15.3},
    "https://www.aac-clyde.space/wp-content/uploads/2021/10/Pulsar-STX-S-band.pdf", "AAC Clyde Space PULSAR-STX data sheet",
    "96 x 90 x 16.9 mm, <100 g, <5 W, 6-12 V (5 V alternative), 2.2-2.3 GHz (STXC) or 2.4-2.45 GHz (STX), up to 2 Mbps, I2C control, SPI payload data, SMA, -25 to +51 C. Mass is the stated upper bound.",
    fields=("dimensions_mm", "mass_g", "rf", "electrical", "thermal"), vendor_country="Sweden / UK", mass_note="upper bound (<100 g) per datasheet",
    rf={"band": "S", "frequency_MHz": [[2200, 2300], [2400, 2450]], "data_rate_bps": {"max": 2000000}}, electrical={"voltage_V": {"min": 6, "max": 12}, "power_W": {"peak": 5}, "interfaces": ["I2C", "SPI"]}, thermal={"operating_temperature_C": {"min": -25, "max": 51}})

# ---- VECTRONIC Aerospace star trackers (product page read 2026-11-11; datasheet PDFs linked there)
add("vectronic_vst_68m", "VECTRONIC Aerospace VST-68M star tracker (with baffle)", "adcs", "star_tracker", "VECTRONIC Aerospace", "VST-68M", (60, 60, 138), 470,
    {"kind": "camera_box_lens", "x": 60, "y": 60, "z": 50, "lens_diameter": 40, "lens_length": 88, "baffle_diameter": 58},
    "https://www.vectronic-aerospace.com/wp-content/uploads/2020/03/VAS-VST68M-DS2.pdf", "VECTRONIC VST-68M data sheet (via vectronic-aerospace.com/star-trackers)",
    "60 x 60 x 138 mm with baffle, 0.470 kg, 3.0 W max, 5 / 30 arcsec (2 sigma, x,y / z). Body/baffle split of the CAD is schematic.", fields=("dimensions_mm", "mass_g", "adcs", "electrical"),
    vendor_country="Germany", adcs={"accuracy_arcsec_2sigma_xy": 5, "accuracy_arcsec_2sigma_z": 30}, electrical={"power_W": {"peak": 3.0}})
add("vectronic_vst_41m", "VECTRONIC Aerospace VST-41M star tracker (with baffle)", "adcs", "star_tracker", "VECTRONIC Aerospace", "VST-41M", (80, 100, 180), 900,
    {"kind": "camera_box_lens", "x": 80, "y": 100, "z": 70, "lens_diameter": 50, "lens_length": 110, "baffle_diameter": 78},
    "https://www.vectronic-aerospace.com/wp-content/uploads/2020/03/VAS-VST41M-DS5.pdf", "VECTRONIC VST-41M data sheet (via vectronic-aerospace.com/star-trackers)",
    "80 x 100 x 180 mm with baffle, 0.7 to 0.9 kg (upper value recorded), 2.5 W max, 18 / 122 arcsec (2 sigma, x,y / z). Body/baffle split of the CAD is schematic.", fields=("dimensions_mm", "mass_g", "adcs", "electrical"),
    vendor_country="Germany", mass_note="upper value of the stated 0.7 to 0.9 kg range", satellite_class="smallsat", adcs={"accuracy_arcsec_2sigma_xy": 18, "accuracy_arcsec_2sigma_z": 122}, electrical={"power_W": {"peak": 2.5}})

# ---- Utah State University Space Dynamics Laboratory DISC camera (brochure read 2026-11-11)
add("usu_sdl_disc_camera", "Space Dynamics Laboratory DISC digital imaging space camera (long configuration)", "payload", "camera", "Utah State University Space Dynamics Laboratory", "DISC", (69.9, 85.3, 212.1), 700,
    {"kind": "camera_box_lens", "x": 69.9, "y": 85.3, "z": 130, "lens_diameter": 60, "lens_length": 82.1},
    "https://sdl.usu.edu/downloads/brochures/disc-camera.pdf", "SDL Digital Imaging Space Camera (DISC) brochure",
    "2.75 x 3.36 x 8.35 in (69.9 x 85.3 x 212.1 mm) in the long configuration (a short configuration is 2.05 x 3.55 x 3.89 in), <0.7 kg, as low as 1 W, 1024 x 1024 or 2560 x 2160 sensors, SERDES / SpaceWire / UART, -40 to +85 C. Mass is the stated upper bound.",
    fields=("dimensions_mm", "mass_g", "payload", "electrical", "thermal"), vendor_country="USA", mass_note="upper bound (<0.7 kg) per brochure", status="in_production",
    payload={"sensor_resolution": ["1024 x 1024", "2560 x 2160"]}, electrical={"power_W": {"nominal": 1.0}, "interfaces": ["SERDES", "SpaceWire", "UART"]}, thermal={"operating_temperature_C": {"min": -40, "max": 85}})

# ---- AZUR SPACE solar cells (data sheets read 2026-11-11). Weight is the datasheet's per-cell value.
AZUR = "https://www.azurspace.com/media/uploads/file_links/file/"
for id, model, document, dims, mass, area, efficiency, vmp, imp, voc, isc in (
        ("azur_4g32c_advanced_hp", "4G32C-Advanced HP bare cell, material 82902", "bdb_00010897-01-00_4g32-advanced_hp_sqvHd09.pdf", (148.06, 60.56, 0.245), 10.4, 77.44, 30.8, 2970, 1097, 3405, 1153),
        ("azur_4g32c_advanced_4x8", "4G32C-Advanced 4 x 8 cm bare cell, material 82921", "bdb_00010895-02-00_4g32-advanced_4x8.pdf", (80.08, 40.08, 0.195), 3.3, 30.60, 31.3, 3015, 433, 3415, 450),
        ("azur_4g32c_advanced_8x8", "4G32C-Advanced 8 x 8 cm bare cell", "bdb_00010896-01-00_4g32-advanced_8x8_qrmHxeq.pdf", (80.0, 80.0, 0.19), 6.5, 60.35, 31.1, 3001, 866, 3415, 900),
        ("azur_4g32a_advanced_8x8_cic", "4G32A-Advanced 8 x 8 cm assembly (CIC with coverglass)", "bdb_00010896-01-00_4g32-advanced_8x8_qrmHxeq.pdf", (80.15, 80.15, 0.32), 8.5, 60.35, 30.7, 3001, 856, 3415, 890),
        ("azur_3g30c_advanced_8x8", "3G30C-Advanced 8 x 8 cm bare cell, material 81780", "bdb_00010892-01-00_tj3g30-advanced_8x8.pdf", (80.0, 80.0, 0.15), 5.2, 60.35, 29.3, 2400, 1008, 2700, 1040),
        ("azur_3g30a_advanced_8x8_cic", "3G30A-Advanced 8 x 8 cm assembly (CIC), material 81752", "bdb_00010892-01-00_tj3g30-advanced_8x8.pdf", (80.15, 80.15, 0.28), 7.1, 60.35, 29.0, 2400, 998, 2700, 1030),
        ("azur_3g30c_advanced_6x12", "3G30C-Advanced 6 x 12 cm bare cell, material 82943", "bdb_00010893-02-00_3g30-advanced_6x12.pdf", (124.3, 60.5, 0.15), 6.1, 71.25, 29.2, 2400, 1185, 2700, 1215)):
    add(id, "AZUR SPACE " + model, "power", "solar_cell", "AZUR SPACE Solar Power GmbH", model, dims, mass, {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]},
        AZUR + document, "AZUR SPACE data sheet " + document.split("_")[1],
        "Outer " + str(dims[0]) + " x " + str(dims[1]) + " mm, " + str(int(dims[2] * 1000)) + " um thick, " + str(mass) + " g per cell, cell area " + str(area) + " cm2, BOL efficiency " + str(efficiency) + " % (AM0 1367 W/m2), Vmp " + str(vmp) + " mV, Imp " + str(imp) + " mA, Voc " + str(voc) + " mV, Isc " + str(isc) + " mA.",
        fields=("dimensions_mm", "mass_g", "electrical"), vendor_country="Germany", fidelity="envelope",
        electrical={"cell_area_cm2": area, "efficiency_percent": efficiency, "vmp_mV": vmp, "imp_mA": imp, "voc_mV": voc, "isc_mA": isc})

# ---- Small-satellite avionics, IMU, propulsion and radios (data sheets read 2026-11-11)
add("beyondgravity_cobc", "Beyond Gravity cOBC constellation on-board computer", "avionics", "obc", "Beyond Gravity", "cOBC", (300, 119, 239), 5400,
    {"kind": "box", "x": 300, "y": 119, "z": 239},
    "https://www.beyondgravity.com/sites/default/files/media_document/2026-02/cOBC_fact_sheet_2026-01-27.pdf", "Beyond Gravity cOBC fact sheet 2026-01-27",
    "300 x 119 x 239 mm excluding mounting feet, 5.4 kg, ~26 W nominal, Power Architecture 2 x e500 at 800 MHz, redundant TM/TC (RS422), Ethernet, SpaceWire, CAN, RS422/RS485, -20 to +60 C.",
    fields=("dimensions_mm", "mass_g", "electrical", "compute", "thermal"), vendor_country="Sweden / Switzerland", satellite_class="smallsat", protrusions="mounting feet are outside the stated 300 x 119 x 239 mm",
    electrical={"power_W": {"nominal": 26}, "interfaces": ["SpaceWire", "Ethernet", "CAN", "RS422", "RS485"]}, compute={"processor": "2 x e500 at 800 MHz"}, thermal={"operating_temperature_C": {"min": -20, "max": 60}})
add("airbus_astrix_ns", "Airbus ASTRIX NS 3-axis fibre-optic gyroscope", "adcs", "imu", "Airbus Defence and Space", "ASTRIX NS", (100, 100, 100), 1400,
    {"kind": "box", "x": 100, "y": 100, "z": 100},
    "https://www.airbus.com/sites/g/files/jlcbta136/files/2022-05/AVIONICS_Astrix_NS_datasheet_2022_v2.pdf", "Airbus ASTRIX NS data sheet 2022 v2",
    "100 x 100 x 100 mm, 1.4 kg, 7 W, 20-52 V bus, bias stability <0.02 deg/h over 1 h, 0.2 deg/h end of life, 2 x RS422/RS485, -20 to 65 C operating.", fields=("dimensions_mm", "mass_g", "adcs", "electrical", "thermal"),
    vendor_country="France", satellite_class="smallsat", adcs={"gyro_bias_stability_deg_h": 0.02}, electrical={"voltage_V": {"min": 20, "max": 52}, "power_W": {"nominal": 7}, "interfaces": ["RS422", "RS485"]}, thermal={"operating_temperature_C": {"min": -20, "max": 65}})
add("cua_fppt_1p7u", "CU Aerospace FPPT 1.7U fibre-fed pulsed plasma thruster", "propulsion", "electric_thruster", "CU Aerospace", "FPPT-1.7U", (217, 90, 86.5), 3030,
    {"kind": "thruster_box_nozzle", "x": 217, "y": 90, "z": 78.5, "nozzle_diameter": 30, "nozzle_length": 8},
    "https://cuaerospace.com/Portals/0/SiteContent/assets/PDF/FPPT-Datasheet%20240807.pdf", "CU Aerospace FPPT data sheet 2024-08-07",
    "21.7 x 9.0 x 8.65 cm envelope (1.7U), 3.03 kg wet, 51 W at 2 Hz (16 W at 0.64 Hz), 0.21 mN at 2 Hz, 29,000 N s total impulse. Nozzle split of the CAD is schematic (PPT electrodes).",
    fields=("dimensions_mm", "mass_g", "propulsion", "electrical"), vendor_country="USA", mass_note="wet mass", propulsion={"type": "pulsed plasma (Teflon fibre fed)", "thrust_N": {"nominal": 0.00021}, "total_impulse_Ns": 29000}, electrical={"power_W": {"nominal": 51}})
add("l3harris_cxs_1000", "L3Harris CXS-1000 S-band multifunction software-defined transponder (core)", "comms", "transponder", "L3Harris", "CXS-1000", (101.6, 106.7, 101.6), 1134,
    {"kind": "box", "x": 101.6, "y": 106.7, "z": 101.6},
    "https://www.l3harris.com/sites/default/files/2022-03/cxs-1000-multifunction-transponder-sell-sheet-sas-61877-v5-web.pdf", "L3Harris CXS-1000 sell sheet SAS-61877 v5",
    "4.0 x 4.2 x 4.0 in core configuration (101.6 x 106.7 x 101.6 mm), 2.5 lb aluminium housing (1.134 kg; 3.6 lb copper), 28 V +- 6 V, receive 1.76-1.84 and 2.025-2.120 GHz, transmit 2.2-2.3 GHz at 10 mW to 20 W RF, 2 kbps to 2 Mbps (20 Mbps capable).",
    fields=("dimensions_mm", "mass_g", "rf", "electrical"), vendor_country="USA", satellite_class="smallsat",
    rf={"band": "S", "frequency_MHz": [[2200, 2300]], "rx_frequency_MHz": [[1760, 1840], [2025, 2120]], "data_rate_bps": {"max": 2000000}}, electrical={"voltage_V": {"min": 22, "max": 34}})
add("enpulsion_ifm_nano", "ENPULSION IFM Nano Thruster (FEEP, first generation)", "propulsion", "electric_thruster", "ENPULSION", "IFM Nano Thruster", (94, 90, 78), 870,
    {"kind": "electric_thruster", "x": 94, "y": 90, "z": 74, "emitter_diameter": 40, "emitter_length": 4},
    "https://www.cubesatshop.com/wp-content/uploads/2017/04/AMR2017-002-03-IFM-Nano-Thruster-Product-Description.pdf", "ENPULSION IFM Nano Thruster product description AMR2017-002-03",
    "94 x 90 x 78 mm, 640 g dry / 870 g wet, 35 W at nominal thrust incl. neutraliser (8-40 W), 350 uN nominal (10 uN to 0.5 mN), Isp 2,000-5,000 s, >5,000 N s. Superseded by the NANO R3.",
    fields=("dimensions_mm", "mass_g", "propulsion", "electrical"), vendor_country="Austria", status="discontinued", mass_note="wet mass", distributors=["direct", "CubeSatShop"],
    propulsion={"type": "FEEP (indium)", "thrust_N": {"nominal": 0.00035}, "isp_s": {"min": 2000, "max": 5000}, "total_impulse_Ns": 5000}, electrical={"power_W": {"nominal": 35}})
IRIS = "https://www.sdl.usu.edu/downloads/brochures/iris-radio.pdf"
for id, name, dims, mass, note, mass_note in (("transponder", "Iris deep-space X-band transponder stack", (101, 101, 56), 875, "Transponder 101 x 101 x 56 mm (~0.5U), 875 g stack.", "stated"),
                                              ("lna", "Iris deep-space radio low-noise amplifier", (114.3, 46.0, 15.5), 125, "LNA 114.3 x 46.0 x 15.5 mm, <=125 g.", "upper bound (<=125 g)"),
                                              ("sspa", "Iris deep-space radio X-band solid-state power amplifier", (102.9, 55.7, 24.4), 230, "SSPA 102.9 x 55.7 x 24.4 mm, <=230 g.", "upper bound (<=230 g)")):
    add("sdl_iris_" + id, "SDL / JPL " + name, "comms", "transponder", "Utah State University Space Dynamics Laboratory (JPL design)", "Iris " + id.upper() if id != "transponder" else "Iris transponder", dims, mass,
        {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]}, IRIS, "SDL Iris radio brochure",
        note + " System 1.1 kg, 35 W DC at 3.8 W RF, 12-28 V, X-band uplink 7.145-7.190 GHz, downlink 8.400-8.450 GHz, UHF receive 390-450 MHz, -20 to +50 C.",
        fields=("dimensions_mm", "mass_g", "rf", "electrical", "thermal"), vendor_country="USA", mass_note=mass_note,
        rf={"band": "X", "frequency_MHz": [[8400, 8450]], "rx_frequency_MHz": [[7145, 7190]]}, electrical={"voltage_V": {"min": 12, "max": 28}, "power_W": {"peak": 35}}, thermal={"operating_temperature_C": {"min": -20, "max": 50}})
add("voyager_uxbt_x_transponder", "Voyager Technologies uXBT X-band transponder", "comms", "transponder", "Voyager Technologies", "uXBT", (153, 127, 116), 3000,
    {"kind": "box", "x": 153, "y": 127, "z": 116},
    "https://voyagertechnologies.com/wp-content/uploads/2025/10/μXBT™-X-BAND-TRANSPONDER-1.pdf", "Voyager uXBT X-band transponder data sheet",
    "153 x 127 x 116 mm, 3 kg, 28 V, 13 W without PA, 80 W with 3 W PA, 110 W with 12 W PA, up to 6 Mbps transmit, 2-12 kbps receive, -20 to +50 C operating.",
    fields=("dimensions_mm", "mass_g", "rf", "electrical", "thermal"), vendor_country="USA", satellite_class="smallsat",
    rf={"band": "X", "data_rate_bps": {"max": 6000000}}, electrical={"voltage_V": {"nominal": 28}, "power_W": {"idle": 13, "peak": 110}}, thermal={"operating_temperature_C": {"min": -20, "max": 50}})

# ---- Blue Canyon Technologies product catalog (read 2026-11-11). Wheels RWp015..RW8 are in smallsat_2026_11_11.py (from the wheel data sheet).
BCT_CATALOG = "https://www.bluecanyontech.com/static/datasheet/BCT-Product-Catalog.pdf"
BCT = dict(vendor_country="USA", distributors=["direct"])
for id, model, dims, mass, shape, note in (
        ("xact15", "XACT-15", (100, 100, 50), 890, {"kind": "box", "x": 100, "y": 100, "z": 50}, "XACT-15 integrated ADCS, 10 x 10 x 5 cm (0.5U), 0.89 kg."),
        ("xact50", "XACT-50", (100, 100, 75.4), 1230, {"kind": "box", "x": 100, "y": 100, "z": 75.4}, "XACT-50 integrated ADCS, 10 x 10 x 7.54 cm (0.75U), 1.23 kg."),
        ("xact100_electronics", "XACT-100 electronics", (100, 100, 50), 520, {"kind": "box", "x": 100, "y": 100, "z": 50}, "XACT-100 electronics unit, 10 x 10 x 5 cm (0.5U) not including external components, 0.52 kg plus 1 kg of external wheels.")):
    add("bct_" + id, "Blue Canyon Technologies " + model + " attitude determination and control unit", "adcs", "adcs_module", "Blue Canyon Technologies", model, dims, mass, shape, BCT_CATALOG, "Blue Canyon Technologies product catalog", note,
        fields=("dimensions_mm", "mass_g"), adcs={"type": "integrated ADCS (star tracker, wheels, torque rods, sun sensors per configuration)"}, **BCT)
for id, model, dims, mass in (("nst_standard", "Standard NST", (100, 55, 50), 350), ("nst_mid", "Mid Extension NST", (170, 85, 70), 450), ("nst_full", "Full Extension NST", (250, 100, 100), 850)):
    add("bct_" + id, "Blue Canyon Technologies " + model + " nano star tracker", "adcs", "star_tracker", "Blue Canyon Technologies", model, dims, mass,
        {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]},
        BCT_CATALOG, "Blue Canyon Technologies product catalog", model + ": " + " x ".join(str(value / 10) for value in dims) + " cm, " + str(mass / 1000) + " kg, <1.5 W at 5 V or <3.5 W at 28 V. Baffle length grows with the extension option.",
        fields=("dimensions_mm", "mass_g", "electrical"), electrical={"power_W": {"peak": 3.5}}, **BCT)
add("bct_rw16", "Blue Canyon Technologies RW16 reaction wheel (16 Nms)", "adcs", "reaction_wheel", "Blue Canyon Technologies", "RW16", (242, 242, 120), 7500,
    {"kind": "reaction_wheel", "x": 242, "y": 242, "z": 120, "housing": "round"}, "https://www.bluecanyontech.com/wp-content/uploads/Reaction-Wheels-1_2025.pdf", "Blue Canyon Technologies Reaction Wheels data sheet 1_2025",
    "242 x 242 x 120 mm, 7.5 kg (catalog: 7.4 kg), 16 Nms, 22-34 V, RS-422, -20 to +60 C operating.", fields=("dimensions_mm", "mass_g", "adcs", "electrical"), satellite_class="smallsat",
    adcs={"momentum_Nms": 16, "max_torque_Nm": 0.25}, electrical={"voltage_V": {"min": 22, "max": 34}, "interfaces": ["RS-422"]}, **BCT)
for id, model, dims, mass, wh, ah in (("battery_1p8s", "Battery 1P8S", (45.7, 106.7, 88.9), 650, 99, 3.4), ("battery_2p8s", "Battery 2P8S", (45.7, 182.9, 88.9), 1200, 198, 6.8)):
    add("bct_" + id, "Blue Canyon Technologies " + model + " Li-ion battery (28 V)", "power", "battery", "Blue Canyon Technologies", model, dims, mass, {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]},
        BCT_CATALOG, "Blue Canyon Technologies product catalog", model + ": footprint " + ("1.8 x 4.2" if "1p8s" in id else "1.8 x 7.2") + " in, 3.5 in high, <" + str(mass) + " g, " + str(wh) + " Wh, " + str(ah) + " Ah, 28 V nominal. Mass is the stated upper bound.",
        fields=("dimensions_mm", "mass_g", "electrical"), mass_note="upper bound per catalog", satellite_class="smallsat", electrical={"energy_Wh": wh, "capacity_mAh": ah * 1000, "voltage_V": {"nominal": 28}}, **BCT)
for id, model, length, mass in (("sada3", "SADA-3", 125, 1500), ("sada3h", "SADA-3H", 150, 1660)):
    add("bct_" + id, "Blue Canyon Technologies " + model + " solar array drive assembly", "mechanisms", "sada", "Blue Canyon Technologies", model, (111, 111, length), mass, {"kind": "cylinder", "diameter": 111, "length": length, "axis": "z"},
        BCT_CATALOG, "Blue Canyon Technologies product catalog", model + ": 11.1 cm diameter x " + str(length / 10) + " cm, " + str(mass / 1000) + " kg, 12 W while manoeuvring.",
        fields=("dimensions_mm", "mass_g", "electrical"), satellite_class="smallsat", electrical={"power_W": {"peak": 12}}, mechanism={"actuator_type": "solar array drive (rotary)"}, **BCT)

# ---- Umbra space systems catalog (read 2026-11-11): bus components sold separately. Dimensions converted from inches as printed.
UMBRA = "https://umbra.space/wp-content/uploads/2026/03/SpaceSystemsCatalog.pdf"
UMBRA_ARGS = dict(vendor_country="USA", distributors=["direct"], satellite_class="smallsat")
for id, name, category, subcategory, part_number, dims, mass, shape, note, extra in (
        ("battery_8s1p", "Battery Module 8S1P", "power", "battery", "5061H10001-1", (181.1, 102.6, 36.3), 930, None, "7.13 x 4.04 x 1.43 in, 0.93 kg, 125 Wh nameplate, 15 A max discharge.", {"electrical": {"energy_Wh": 125, "configuration": "8S1P"}}),
        ("battery_8s2p", "Battery Module 8S2P", "power", "battery", "5061H10001-2", (181.1, 102.4, 63.5), 1460, None, "7.13 x 4.03 x 2.50 in, 1.46 kg, 250 Wh nameplate, 20 A max discharge.", {"electrical": {"energy_Wh": 250, "configuration": "8S2P"}}),
        ("magnetorquer_6", "Magnetorquer 6", "adcs", "magnetorquer", "5031H10001-1", (129.5, 36.6, 22.2), 300, None, "5.100 x 1.440 x 0.875 in, 300 g, 4.24 W peak.", {"electrical": {"power_W": {"peak": 4.24}}}),
        ("mss_package", "MSS (magnetometer / sun sensor) package", "adcs", "sun_sensor", "5041H10001-1", (51.3, 37.3, 23.1), 65, None, "2.02 x 1.47 x 0.91 in, <65 g, <170 mW at 5 V. Mass is the stated upper bound.", {"mass_note": "upper bound (<65 g) per catalog", "electrical": {"power_W": {"nominal": 0.17}}}),
        ("network_switch_8_1g", "Network Switch 8-1G", "avionics", "network_switch", "5091H10001-1", (148.3, 80.0, 24.6), 300, None, "5.84 x 3.15 x 0.97 in, <300 g, 5.4 W peak at 33 V, 4.6 W average at 28 V. Mass is the stated upper bound.", {"mass_note": "upper bound (<300 g) per catalog", "electrical": {"power_W": {"nominal": 4.6, "peak": 5.4}}}),
        ("reaction_wheel", "Reaction Wheel", "adcs", "reaction_wheel", "5021H10001-1", (152.4, 152.4, 38.1), 2000, {"kind": "reaction_wheel", "x": 152.4, "y": 152.4, "z": 38.1}, "6.0 x 6.0 x 1.5 in, 2 kg, 100 W peak at max torque, 5 W steady state.", {"electrical": {"power_W": {"nominal": 5, "peak": 100}}}),
        ("s_band_radio", "S-Band Radio", "comms", "transceiver", "5111H10001-1", (122.4, 94.0, 20.6), 300, None, "4.82 x 3.7 x 0.812 in, <300 g, 15.7 W peak transmitting, 4.4 W receiving. Mass is the stated upper bound.", {"mass_note": "upper bound (<300 g) per catalog", "rf": {"band": "S"}, "electrical": {"power_W": {"nominal": 4.4, "peak": 15.7}}}),
        ("solar_array", "Solar Array (stowed)", "power", "solar_panel", "5081H10001-1", (326.9, 328.9, 73.7), 2500, None, "Stowed 326.9 x 328.9 x 73.7 mm, deployed 40 x 13 x 10 in, 2.5 kg, 120 W BOL at 28 C AM0.", {"electrical": {"power_W": {"nominal": 120}}}),
        ("syncrelease_4", "SyncRelease 4 separation system", "mechanisms", "separation_system", "5011H10001-1", (449.6, 499.9, 88.4), 6400, None, "17.700 x 19.680 x 3.480 in, 6.40 kg total (5.48 kg lower, 0.92 kg upper), <4.5 W peak, 3 W average at 24 V.", {"electrical": {"power_W": {"nominal": 3.0, "peak": 4.5}}})):
    extra = dict(extra)
    extra.update(UMBRA_ARGS)
    add("umbra_" + id, "Umbra " + name + " (part " + part_number + ")", category, subcategory, "Umbra", name + " " + part_number, dims, mass, shape or {"kind": "box", "x": dims[0], "y": dims[1], "z": dims[2]},
        UMBRA, "Umbra Space Systems Catalog (2026-03)", note, fields=("dimensions_mm", "mass_g", "electrical"), **extra)

# ---- Voyager S-band transponders and SatNOGS COMMS
for id, model, receive in (("usgls_100", "uSGLS-100", "1-2 kbps"), ("ustdn_100", "uSTDN-100", "up to 256 kbps")):
    add("voyager_" + id, "Voyager Technologies " + model + " S-band transponder", "comms", "transponder", "Voyager Technologies", model, (127, 127, 101.6), 2100, {"kind": "box", "x": 127, "y": 127, "z": 101.6},
        "https://voyagertechnologies.com/wp-content/uploads/2026/04/μSGLS-100™-S-BAND-TRANSPONDER-1.pdf" if id == "usgls_100" else "https://voyagertechnologies.com/wp-content/uploads/2025/10/μSTDN-100™-S-BAND-TRANSPONDER-1.pdf", "Voyager " + model + " transponder data sheet",
        "5 x 5 x 4 in (127 x 127 x 101.6 mm), 2.1 kg transponder only, 28 +- 6 V, 35 W max transmit at 5 W RF, 6 W max receive, up to 5 Mbps transmit, " + receive + " receive, -30 to +65 C.",
        fields=("dimensions_mm", "mass_g", "rf", "electrical", "thermal"), vendor_country="USA", satellite_class="smallsat",
        rf={"band": "S"}, electrical={"voltage_V": {"min": 22, "max": 34}, "power_W": {"idle": 6, "peak": 35}}, thermal={"operating_temperature_C": {"min": -30, "max": 65}})
add("libre_space_satnogs_comms", "Libre Space Foundation SatNOGS-COMMS UHF + S-band transceiver", "comms", "transceiver", "Libre Space Foundation", "SatNOGS-COMMS", (90, 90, 25), 200,
    {"kind": "pc104_board", "x": 90, "y": 90, "z": 1.6, "components_height": 23.4},
    "https://satnogs.org/wp-content/uploads/sites/2/2022/08/SatNOGS-COMMS-Product-flyer-1.pdf", "SatNOGS-COMMS product flyer",
    "90 x 90 x 25 mm, <200 g with aluminium shield, 6-14 V, 8 W peak (31 dBm S-band), dual radio UHF and S-band half duplex, CAN-FD / UART / I2C / SPI / LVDS, -40 to +85 C. Open-source hardware. Mass is the stated upper bound.",
    fields=("dimensions_mm", "mass_g", "rf", "electrical", "thermal"), vendor_country="Greece", mass_note="upper bound (<200 g) per flyer",
    rf={"band": "UHF + S"}, electrical={"voltage_V": {"min": 6, "max": 14}, "power_W": {"peak": 8}, "interfaces": ["CAN-FD", "UART", "I2C", "SPI", "LVDS"]}, thermal={"operating_temperature_C": {"min": -40, "max": 85}})

# ---- Xiphos Q-cards (spec sheets read 2026-11-11)
XIPHOS = dict(vendor_country="Canada", distributors=["direct"])
add("xiphos_q8", "Xiphos Q8 hybrid processor card (Zynq UltraScale+, with connectors)", "avionics", "obc", "Xiphos Systems (Epiq)", "Q8", (85.8, 80, 22.6), 64,
    {"kind": "pc104_board", "x": 85.8, "y": 80, "z": 1.6, "components_height": 21.0},
    "https://resources.epiqsolutions.com/hubfs/Xiphos-2023/PDFs/XTI-2001-2024-i-Q8-Rev-C-Spec-Sheet.pdf?hsLang=en", "Xiphos Q8 spec sheet XTI-2001-2024 rev C",
    "85.8 x 80 x 22.6 mm and 64 g with the RJ45 and power connectors (80 x 80 x 11.2 mm, 56 g without), 5 W typical, 6-15 V, Zynq UltraScale+ XCZU7EG (4 x A53 at 1.2 GHz, 2 x R5), Gigabit Ethernet, USB-C, CAN, -40 to +60 C.",
    fields=("dimensions_mm", "mass_g", "electrical", "compute", "thermal"), electrical={"voltage_V": {"min": 6, "max": 15}, "power_W": {"nominal": 5}, "interfaces": ["Ethernet", "USB", "CAN", "RS-422/485"]}, compute={"processor": "Xilinx Zynq UltraScale+ XCZU7EG"}, thermal={"operating_temperature_C": {"min": -40, "max": 60}}, **XIPHOS)
add("xiphos_q8j", "Xiphos Q8J / Q8JS processor card (board only)", "avionics", "obc", "Xiphos Systems (Epiq)", "Q8J", (80, 80, 11.2), 56,
    {"kind": "pc104_board", "x": 80, "y": 80, "z": 1.6, "components_height": 9.6},
    "https://resources.epiqsolutions.com/hubfs/Xiphos-2023/PDFs/XTI-2001-2026-e-Q8J-Rev-B-Spec-Sheet.pdf?hsLang=en", "Xiphos Q8J spec sheet XTI-2001-2026 rev B",
    "80 x 80 x 11.2 mm, 56 g excluding connectors, ~6 W typical, 6-15 V, Zynq UltraScale+ XCZU7EG, Ethernet via adapter board, USB-C, CAN, PCIe, -40 to +60 C.",
    fields=("dimensions_mm", "mass_g", "electrical", "compute", "thermal"), protrusions="RJ45 adapter and connectors are outside the 80 x 80 x 11.2 mm board envelope",
    electrical={"voltage_V": {"min": 6, "max": 15}, "power_W": {"nominal": 6}, "interfaces": ["Ethernet", "USB", "CAN", "PCIe"]}, compute={"processor": "Xilinx Zynq UltraScale+ XCZU7EG"}, thermal={"operating_temperature_C": {"min": -40, "max": 60}}, **XIPHOS)
add("xiphos_q7s", "Xiphos Q7S processor card (Zynq-7020, with RJ45)", "avionics", "obc", "Xiphos Systems (Epiq)", "Q7S", (78, 43, 19), 32,
    {"kind": "pc104_board", "x": 78, "y": 43, "z": 1.6, "components_height": 17.4},
    "https://www.aac-clyde.space/wp-content/uploads/2021/10/XTI_Q7_S_Datasheet_Ver_20160602_a8b5d40828.pdf", "Xiphos Q7S datasheet (2016-06-02, via AAC Clyde Space)",
    "78 x 43 x 19 mm and 32 g with the RJ45 connector (78 x 43 x 9 mm, 24 g without), typ. 1 W, 6-28 V, Zynq-7020 dual Cortex-A9 up to 766 MHz, Gigabit Ethernet, USB 2.0, RS232/422/485, -40 to +85 C.",
    fields=("dimensions_mm", "mass_g", "electrical", "compute", "thermal"), electrical={"voltage_V": {"min": 6, "max": 28}, "power_W": {"nominal": 1}, "interfaces": ["Ethernet", "USB", "RS-232/422/485"]}, compute={"processor": "Xilinx Zynq-7020"}, thermal={"operating_temperature_C": {"min": -40, "max": 85}}, **XIPHOS)

# ---- Beyond Gravity GNSS receiver and antennas, JAVAD SpaceAnt (data sheets read 2026-11-11)
add("beyondgravity_navrix_pinpoint", "Beyond Gravity NavRIX PinPoint dual-frequency GNSS receiver", "adcs", "gnss_receiver", "Beyond Gravity", "NavRIX PinPoint", (210, 155, 112), 3600,
    {"kind": "box", "x": 210, "y": 155, "z": 112},
    "https://www.beyondgravity.com/sites/default/files/media_document/2023-11/NavRIX-PinPoint-GNSS%20Receiver.pdf", "Beyond Gravity NavRIX PinPoint data sheet",
    "210 x 155 x 112 mm including feet, 3.6 kg, 10 W average, 28 V unregulated, GPS L1 C/A, L5, L2C, Galileo E1, E5a, 2 antenna inputs, RS-422 UART (CAN optional), PPS, -20 to +60 C.",
    fields=("dimensions_mm", "mass_g", "electrical", "thermal"), vendor_country="Sweden / Austria", satellite_class="smallsat",
    electrical={"voltage_V": {"nominal": 28}, "power_W": {"nominal": 10}, "interfaces": ["RS-422", "CAN (optional)"]}, thermal={"operating_temperature_C": {"min": -20, "max": 60}})
BG_GNSS_ANTENNAS = "https://www.beyondgravity.com/sites/default/files/media_document/2023-11/Antennas-for-GNSS-receivers.pdf"
for id, name, diameter, height, mass, bands, connector in (("extended_pec", "Extended GNSS PEC antenna", 200, 87, 735, "L5/E5a, E5b, L2, L1/E1", "SMA female"),
                                                          ("pec", "GNSS PEC antenna", 160, 55, 325, "L5/E5a, E5b, L2, L1/E1", "SMA female"),
                                                          ("geo_pec", "GEO GNSS PEC antenna", 239, 179, 715, "L1/E1 (GLONASS G1)", "SMA female"),
                                                          ("l1_pec", "L1 PEC antenna", 144, 35, 220, "L1/E1 (GLONASS G1)", "SMA female"),
                                                          ("helix", "GNSS helix antenna", 90, 410, 815, "L5/E5a, L2, L1/E1", "TNC female")):
    add("beyondgravity_gnss_antenna_" + id, "Beyond Gravity " + name, "adcs", "gnss_antenna", "Beyond Gravity", name, (diameter, diameter, height), mass, {"kind": "radome_puck", "diameter": diameter, "length": height},
        BG_GNSS_ANTENNAS, "Beyond Gravity antennas for GNSS receivers data sheet", "Diameter " + str(diameter) + " mm, maximum height " + str(height) + " mm, " + str(mass) + " g, bands " + bands + ", " + connector + " connector.",
        fields=("dimensions_mm", "mass_g", "rf"), vendor_country="Sweden", satellite_class="smallsat", rf={"band": bands, "antenna_type": "GNSS " + ("helix" if id == "helix" else "patch-excited cup")})
add("javad_spaceant", "JAVAD SpaceAnt OEM multi-GNSS antenna", "adcs", "gnss_antenna", "JAVAD GNSS", "SpaceAnt OEM", (70.1, 70.1, 16.6), 62,
    {"kind": "patch_antenna", "x": 70.1, "y": 70.1, "z": 14.6, "patch_inset": 14, "patch_height": 2.0},
    "https://download.javad.com/sheets/SpaceAnt_Datasheet_250722.pdf", "JAVAD SpaceAnt data sheet 2025-07-22",
    "70.1 x 70.1 x 16.6 mm, 62 g, LNA gain 32 +- 2 dB, GPS L1/L2/L5, GLONASS, Galileo E1/E5, BeiDou, QZSS, SBAS, NavIC, L-band 1525-1559 MHz, -45 to +85 C operating.",
    fields=("dimensions_mm", "mass_g", "rf", "thermal"), vendor_country="USA", rf={"band": "multi-GNSS", "antenna_type": "active patch", "lna_gain_dB": 32}, thermal={"operating_temperature_C": {"min": -45, "max": 85}})
