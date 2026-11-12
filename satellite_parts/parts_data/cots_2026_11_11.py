"""Off-the-shelf (COTS) components added 2026-11-11: industrial parts that small satellites use, read from the manufacturer datasheet.
Rule: dimensions and mass are the datasheet's own values."""
from parts_data._common import part, source, cost

PARTS = []

# ---- Analog Devices MEMS IMUs (data sheets read 2026-11-11)
for id, model, url, dims, mass, gyro_range, bias_stability, accel_range, current_mA, shape in (
        ("adis16488a", "ADIS16488A", "https://www-cce.cldnet.analog.com/media/en/technical-documentation/data-sheets/ADIS16488A.pdf", (47, 44, 14), 48, 450, 5.1, 18, 245, {"kind": "box", "x": 47, "y": 44, "z": 14}),
        ("adis16495", "ADIS16495", "https://wcm-cce.cldnet.analog.com/media/en/technical-documentation/data-sheets/ADIS16495.pdf", (47, 44, 14), 42, 450, 0.8, 8, 89, {"kind": "box", "x": 47, "y": 44, "z": 14}),
        ("adis16475", "ADIS16475", "https://www-cce.cldnet.analog.com/media/en/technical-documentation/data-sheets/ADIS16475.pdf", (11, 15, 11), 1.3, 2000, 2.0, 8, 44, {"kind": "box", "x": 11, "y": 15, "z": 11})):
    PARTS.append(part("adi_" + id, "Analog Devices " + model + " MEMS inertial measurement unit", "adcs", "imu", "Analog Devices", model, dims, mass, shape,
        source("datasheet", url, "Analog Devices " + model + " data sheet", ["dimensions_mm", "mass_g", "adcs", "electrical", "thermal"], notes="Package approximately " + " x ".join(str(value) for value in dims) + " mm, " + str(mass) + " g (device weight table), 3.0 to 3.6 V single supply, " + str(current_mA) + " mA typical normal mode, gyro up to +-" + str(gyro_range) + " deg/s, in-run bias stability " + str(bias_stability) + " deg/h (best range model), accelerometer +-" + str(accel_range) + " g, SPI, -40 to +105 C. Commercial part, not space qualified."),
        vendor_country="USA", distributors=["Digi-Key", "Mouser", "Analog Devices"], status="in_production", fidelity="envelope", satellite_class="cubesat_and_smallsat",
        adcs={"gyro_range_deg_s": gyro_range, "gyro_bias_stability_deg_h": bias_stability, "accel_range_g": accel_range}, electrical={"voltage_V": {"min": 3.0, "max": 3.6}, "current_mA": current_mA, "interfaces": ["SPI"]},
        thermal={"operating_temperature_C": {"min": -40, "max": 105}}, cost=cost(basis="distributor")))

# ---- DCUBED micro pin puller (data sheet read 2026-11-11; values marked preliminary by DCUBED)
PARTS.append(part("dcubed_ud3pp", "DCUBED uD3PP micro pin puller (shape-memory alloy)", "mechanisms", "pin_puller", "DCUBED (Deployables Cubed GmbH)", "uD3PP", (25.5, 25.5, 25.5), 80,
    {"kind": "box", "x": 25.5, "y": 25.5, "z": 25.5},
    source("datasheet", "https://www.cubesatshop.com/wp-content/uploads/2022/12/D3-1-13-TDS-DataSheet_uD3PP-6.pdf", "DCUBED uD3PP technical data sheet", ["dimensions_mm", "mass_g", "mechanism", "electrical", "thermal"], notes="25.5 x 25.5 x 25.5 mm (standard interface), about 80 g, 6.5 mm stroke, about 150 N maximum actuation sideload, 1.6 to 2 A DC actuation, 1.2 +- 0.2 ohm, -35 to 80 C (TBC). All values marked preliminary by DCUBED."),
    vendor_country="Germany", distributors=["direct", "CubeSatShop"], status="in_production", fidelity="envelope", satellite_class="cubesat_and_smallsat",
    mechanism={"actuator_type": "shape_memory_alloy pin puller", "stroke_mm": 6.5, "max_sideload_N": 150}, electrical={"current_A": {"min": 1.6, "max": 2.0}, "resistance_ohm": 1.2},
    thermal={"operating_temperature_C": {"min": -35, "max": 80}}, cost=cost(basis="quote")))
