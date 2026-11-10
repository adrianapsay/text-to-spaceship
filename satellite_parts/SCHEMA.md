# satellite_parts: part record schema (part.json)

Every part folder holds part.stl, part.step (and part_deployed.stl/.step for deployables) and part.json with these fields.
Numbers are SI-derived with explicit units in the field name (mm, g, V, W, Wh, mNm, mNms, N, s, MPa, K). null = not published by the source. Nothing is estimated silently: an estimated value carries "_note" with the rule and the source type says derived or unverified.

identity
  id, name, category, subcategory, vendor, vendor_country, model, variant, status (in_production | discontinued | in_development | unknown),
  first_available_year, first_flight_year, flight_heritage (count or text), distributors [list], lead_time, cost {value, currency, basis (list_price | quote | unknown), source}
geometry
  dimensions_mm {x, y, z} (as packed; stowed for deployables), deployed_dimensions_mm, envelope_note, fidelity (envelope | envelope_plus_features | detailed),
  mounting {face, pattern, fasteners}, mass_g, material, density_g_cm3 (used for the STL), center_of_mass_note
electrical  voltage_V {min, nominal, max}, power_W {idle, nominal, peak}, energy_Wh, capacity_Ah, capacitance_F, interfaces [list]
compute     clock_GHz, ram_MB, storage_GB, processor, os
rf          band, frequency_MHz, data_rate_kbps, tx_power_W, gain_dBi, polarization
propulsion  propellant, thrust_mN {min, nominal, max}, isp_s, total_impulse_Ns, propellant_mass_g, tank_pressure_MPa, power_W
adcs        momentum_mNms, torque_mNm, max_speed_rpm, dipole_Am2, accuracy_deg, fov_deg, update_rate_Hz, pointing_knowledge_arcsec
mechanism   actuation_time_s, actuation_force_N, stroke_mm, cycles, actuator_type (burn_wire | pin_puller | motor | spring | HDRM)
thermal     operating_temperature_C {min, max}, survival_temperature_C, dissipation_W
environment radiation_TID_krad, vibration_g_rms, vacuum_qualified, trl
source      type (datasheet | standard | derived | unverified), url, document (title, revision, date), accessed, fields_from_source [list], notes

interfaces  (added for compatibility checks) data_buses [I2C, CAN, SPI, UART, RS-422, RS-485, USB, Ethernet, ...] parsed from the datasheet interface list;
            mechanical (e.g. "PC/104 stack", "M3 x 4 base pattern", "CDS rails"); electrical_connectors [e.g. "Samtec ESQ PC/104 stack-through", "Harwin Gecko G125 2x10", "Micro-D 9", "pigtail"]; rf_connectors [e.g. "SMA female", "MMCX"]; power_bus_V (nominal supply)
            Null or empty means the datasheet did not state it; nothing here is guessed.
