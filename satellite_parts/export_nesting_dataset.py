"""
Exports a set of catalog parts as a nesting_bench dataset folder (one STL per part plus densities.csv with each part's effective density).
    python export_nesting_dataset.py --out ../nesting_bench/datasets_satellite/cubesat_3u_bus --ids isis_structure_3u isis_iobc gomspace_nanopower_bp4 ...
    python export_nesting_dataset.py --out ../nesting_bench/datasets_satellite/adcs_mix --category adcs --max_parts 30
    python export_nesting_dataset.py --out ... --preset 3u_bus
Then: NESTING_DATASETS_FOLDER=../nesting_bench/datasets_satellite python ../nesting_bench/benchmark.py --dataset cubesat_3u_bus ...
Deployed geometry is never exported (packing is done stowed).
"""
import os
import csv
import json
import shutil
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
PRESETS = {
    "3u_bus": ["isis_structure_3u", "isis_iobc", "isis_ieps_type_b", "isis_ieps_battery_4cell", "isis_trxvu", "isis_antenna_system", "isis_imtq", "cubespace_cubewheel_cw0057", "cubespace_cubewheel_cw0057", "cubespace_cubewheel_cw0057", "cubespace_cubestar", "cubespace_cubesense_sun", "novatel_oem719", "calian_tw1322_gnss_antenna", "gomspace_nanocam_c1u_35mm", "isis_solar_panel_3u", "isis_solar_panel_3u", "pc104_standoff_m3_15p24", "pc104_standoff_m3_15p24", "pc104_standoff_m3_15p24", "pc104_standoff_m3_15p24", "shcs_m3x8", "shcs_m3x8", "shcs_m3x8", "shcs_m3x8"],
    "6u_bus": ["gomspace_nanostruct_6u_mk2", "gomspace_nanomind_a3200", "gomspace_nanopower_p60_dock", "gomspace_nanopower_bp8_100wh", "gomspace_nanocom_ax100", "gomspace_nanocom_ant6f_uhf", "gomspace_nanotorque_gst600_mk2", "gomspace_nanotorque_gsw600_pyramid", "aac_st400", "aac_ss200", "aac_ss200", "aac_gnss_701", "aac_ant_gps", "enpulsion_nano_r3", "simera_triscape100", "gomspace_msp_a_6_1", "gomspace_msp_a_6_1", "endurosat_xband_transmitter_2026", "endurosat_xband_4x4_patch"],
    "adcs_only": ["cubespace_cubewheel_cw0017", "cubespace_cubewheel_cw0162", "cubespace_cubetorquer_cr0006", "cubespace_cubetorquer_cr0006", "cubespace_cubetorquer_cr0006", "cubespace_cubestar", "aac_rw400_15", "aac_mtq800", "aac_mag3", "aac_pg400", "nss_aquila_h01", "rocketlab_rw006", "rocketlab_st16rt2", "arcsec_sagitta", "sensonor_stim277h", "epson_m_g370pds"],
}
parser = argparse.ArgumentParser()
parser.add_argument("--out", required=True)
parser.add_argument("--ids", nargs="*", default=None)
parser.add_argument("--preset", choices=sorted(PRESETS), default=None)
parser.add_argument("--category", default=None)
parser.add_argument("--max_parts", type=int, default=60)
parser.add_argument("--max_side_mm", type=float, default=None, help="skip parts whose longest side exceeds this")
arguments = parser.parse_args()

rows = list(csv.DictReader(open(os.path.join(HERE, "catalog.csv"))))
by_id = {row["id"]: row for row in rows}
ids = []
if arguments.preset:
    ids = list(PRESETS[arguments.preset])
if arguments.ids:
    ids += arguments.ids
if arguments.category:
    ids += [row["id"] for row in rows if row["category"] == arguments.category][:arguments.max_parts]
if not ids:
    raise SystemExit("give --ids, --preset or --category")
os.makedirs(arguments.out, exist_ok=True)
counts = {}
density_lines = []
manifest = []
for part_id in ids:
    row = by_id.get(part_id)
    if row is None:
        print("unknown id " + part_id)
        continue
    longest = max(float(row["x_mm"]), float(row["y_mm"]), float(row["z_mm"]))
    if arguments.max_side_mm and longest > arguments.max_side_mm:
        print("skipping " + part_id + " (longest side " + str(longest) + " mm)")
        continue
    counts[part_id] = counts.get(part_id, 0) + 1
    name = part_id if counts[part_id] == 1 else part_id + "_" + str(counts[part_id])
    source_folder = os.path.join(HERE, row["category"], part_id)
    shutil.copy(os.path.join(source_folder, "part.stl"), os.path.join(arguments.out, name + ".stl"))
    record = json.load(open(os.path.join(source_folder, "part.json")))
    density = record["geometry"].get("effective_density_g_cm3") or 1.0
    density_lines.append(name + "," + str(density))
    manifest.append({"name": name, "part_id": part_id, "category": row["category"], "vendor": row["vendor"], "mass_g": row["mass_g"], "dimensions_mm": [row["x_mm"], row["y_mm"], row["z_mm"]], "effective_density_g_cm3": density})
open(os.path.join(arguments.out, "densities.csv"), "w").write("\n".join(density_lines) + "\n")
json.dump(manifest, open(os.path.join(arguments.out, "manifest.json"), "w"), indent=1)
print(str(len(manifest)) + " parts written to " + arguments.out)
