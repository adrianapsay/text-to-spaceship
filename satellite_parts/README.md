# satellite_parts

A library of 3D parts for CubeSats and small satellites, built for the Text to Spaceship capstone (UC Berkeley MEng #156). Every part has simple watertight geometry (STEP + STL), a structured record with the engineering data a design engine needs (mass, dimensions, electrical, compute, RF, propulsion, ADCS, thermal, interfaces, cost, availability, age), a source record that says where each number came from, an STL preview image, and links to the supplier photo and datasheet.

Status at 2026-11-10: 406 parts (colored multi-body geometry, 222 supplier photos and 118 datasheet pages fetched, drawings for all), about 60 vendors, 12 categories. Source quality and flag counts are in catalog.csv and needs_verification.csv (regenerated with every build).

## Layout

```
satellite_parts/
  <category>/<part_id>/part.step, part.stl       geometry as packed (stowed), centered on its bounding box, mm
                        part_deployed.step/.stl  deployed state when one exists (antennas, hinged arrays)
                        part.json                the record (see SCHEMA.md)
                        bodies/<stem>__<body>.stl  one STL per colored body (housing, flywheel, nozzle, cells, ...); part.stl is their union
                        preview.png              colored render of the bodies (and the deployed state)
                        drawing.png              three-view dimension drawing of part.stl (make_drawings.py)
                        reference_photo.jpg      supplier / marketplace photo, 400 px (fetch_reference_images.py); photo_source.txt when it came from a web image search (representative)
                        datasheet_page1.png      first page of the datasheet (same script)
  catalog.csv              one row per part (image, id, category, vendor, model, status, size, mass, material, source type and url, year, cost, faces)
  references.csv           photo url, photo source, product page, datasheet url per part
  needs_verification.csv   parts with unverified or derived sources, estimated masses or assumed dimensions
  downloads.csv            vendor CAD links (STEP/zip) to download by hand or script
  catalog_explorer.html    self-contained browser: filters, thumbnails, 3D viewer, full records, similar parts
  catalog_images.html      contact sheet with STL preview, supplier photo and datasheet page (after fetching)
  parts_data/*.py          the source of truth: one module per category, one record per part
  parts_data/_references.py photo and datasheet links keyed by part id or id prefix
  shapes.py                build123d geometry builders (box, cylinder, pc104_board, cubesat_frame, reaction_wheel, screw, ...)
  generate_parts.py        builds everything above from parts_data
  make_catalog_explorer.py builds catalog_explorer.html
  make_catalog_page.py     builds catalog_images.html
  make_drawings.py         writes drawing.png for every part
  fetch_reference_images.py downloads photos and datasheets (run on a machine with web access)
  check_library.py         consistency checks (bbox vs declared size, watertight, density, missing fields); exit 1 on problems
  export_nesting_dataset.py writes a nesting_bench dataset folder (STLs + densities.csv + manifest.json) from catalog ids, a preset (3u_bus, 6u_bus, adcs_only) or a category
  SCHEMA.md                field definitions
```

## Build

```
pip install build123d trimesh numpy pyvista pillow requests pymupdf
python generate_parts.py --render        # geometry, records, CSVs, previews (on Linux without a display: xvfb-run python generate_parts.py --render)
python fetch_reference_images.py         # supplier photos + datasheets into each part folder, then catalog_images.html
python make_drawings.py                  # drawing.png per part
python make_catalog_explorer.py          # catalog_explorer.html
python check_library.py                  # consistency checks, run after every build
```

`generate_parts.py --only power comms` rebuilds selected categories (it rewrites the CSVs with only those rows, so run the full build afterwards).

## Sourcing policy

Every record has `source.type`:

- `datasheet`: dimensions and mass read from the vendor datasheet, product page spec table, or a marketplace listing that reproduces the datasheet (satsearch, satcatalog). `source.document` holds title, revision and date where the document states them; `source.fields_from_source` lists which fields came from it.
- `standard`: taken from a public standard (CubeSat Design Specification Rev 14.1, PC/104, ISO 4762/4032/7089).
- `derived`: computed from a standard or a stated spec (bar stock from density, connector outline from pitch, generic radiator plates). `source.notes` says how.
- `unverified`: the vendor does not publish the dimension or the page could not be read; the value is an assumption or from memory. `source.notes` says which fields are assumed. These parts must be checked before use in a design.

`mass_note`, `dimensions_note` and `cost_note` flag individual estimated values even on datasheet-sourced parts. needs_verification.csv collects all of this.

Availability: `status` is `in_production`, `legacy` (no longer on the vendor's current product list; 2022 catalogue items from EnduroSat and several GomSpace NanoPower / NanoCom products are marked this way with a `status_note`), `discontinued` or `unknown`. `first_available_year` and `first_flight_year` are filled where a dated datasheet or vendor page gives them.

Photos: references.csv lists a supplier or marketplace photo URL for about 170 parts and a datasheet PDF for about 160. The cloud session that built this library cannot download from vendor sites, so fetch_reference_images.py pulls them on your machine. Marketplace photos (cdn.satsearch.com, satcatalog) are the vendor's own product photos re-hosted by those sites; `photo_source` says which site and notes when a family photo stands in for a specific model.

## Geometry conventions

- Units mm. Each part is centered on its bounding box; `dimensions_mm` is the as-packed envelope (x, y, z) and `geometry.measured_bbox_mm` is measured from the STL.
- Fidelity is deliberately low: boxes, cylinders, PC/104 outlines with corner holes, skeleton frames, flywheel discs, screw heads with hex sockets, tape antennas. `fidelity` is `envelope` or `envelope_plus_features`. Face counts are in `geometry.face_counts` (max 716 at the default 0.15 mm tolerance).
- `geometry.effective_density_g_cm3` = mass / STL volume, useful for spotting envelope models that are mostly air.
- Deployed states are separate solids (`part_deployed.*`) with their own `deployed_dimensions_mm`.

## Interfaces block

`interfaces` in part.json is for compatibility checks: `data_buses` (I2C, CAN, SPI, UART, RS-422, RS-485, USB, Ethernet, PPS, GPIO, JTAG, CSP parsed from the electrical interfaces), `mechanical` (mounting pattern, PC/104 stack), `electrical_connectors` (stated connector types), `rf_connectors` (SMA, SMP, MCX, MMCX, pigtails), `power_bus_V` (nominal supply). Two parts can be joined electrically when they share a bus and a connector family, or when one provides the bus the other consumes; mechanical joining needs matching mounting patterns.

## Known gaps

- Thermal: vendor parts are limited to TAI CuTS straps and Minco heater classes; heat pipes, MLI and radiators are generic.
- Payload: four cameras. Hyperspectral, radio science and other instruments are not covered.
- Dimensions for most EnduroSat modules, NPC Spacemind and DHV panels, the ST-16RT2 and the COTS Li-ion cells are unverified because the vendor pages do not state them or the PDF could not be opened from the build session.
- Costs are mostly `quote`; only fasteners, stock, cells and a few COTS parts carry a price.

## Using the parts in the nesting benchmark

```
python export_nesting_dataset.py --out ../nesting_bench/datasets_satellite/3u_bus --preset 3u_bus
cd ../nesting_bench
python benchmark.py --datasets_folder datasets_satellite --datasets 3u_bus_inner --algorithms empty_maximal_spaces heightfield_drop --k 8 --trials 10 --mode container --container 90 90 320 --clearance 1 --voxel_pitch 4 --name satellite_3u
```

Leave the structure out of the part set and use its interior as the container (a 3U frame leaves roughly 90 x 90 x 320 mm). Large flat parts (solar panels, 325 mm long) make the voxel point clouds slow at 2 mm pitch; use `--voxel_pitch 4` or pack them separately. Smoke test on 2026-11-08: 8 inner parts of the 3U preset, empty_maximal_spaces, container mode, 0.355 density, all valid, 0.05 s per trial.

## Local catalog explorer (same page as the published artifact, from the part folders on your machine)
    python catalog_local.py           (Windows: double-click OPEN_CATALOG.bat)
Rebuilds `catalog_local.html` from catalog.csv and the part folders only when something changed (seconds), then opens it in the browser. Works offline for everything in the page (records, renders, photos, datasheet thumbnails, 3D viewer; three.js r128 is bundled from vendor/, MIT); links to vendor pages and datasheet PDFs need the internet. `--rebuild` forces a build, `--no-open` builds without opening. After changing parts in parts_data/, run `generate_parts.py --render` first. `make_catalog_explorer.py` (no flags) still writes `catalog_explorer.html`, the page published as the artifact. Needs numpy, trimesh and pillow (requirements.txt).
