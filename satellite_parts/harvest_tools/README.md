# Harvest tools (2026-11-11)

How the web-harvested parts were collected and vetted. The download scripts ran on a lab laptop (the cloud workspace cannot reach most sites).

1. `harvest_catalogs.py` (laptop): crawls satcatalog / satsearch product pages, writes `pass6_index.csv`, page texts and up to 1200 data sheets (text + first page image + product photo).
2. `harvest_more.py` (laptop): second round on the same index; photos from data sheet PDFs where the page has none.
3. `extract_pass6_candidates.py`: finds stated dimensions (a x b x c with units) and mass in each data sheet text.
4. `vet_pass6.py`: keeps a row only if a size word is next to the dimensions, the mass agrees with the catalog page (within 12 %), the type is a component, it is not a duplicate of a catalog part and it does not share one family sheet with another row.
5. `p6_reject.txt`: rows removed by hand after reading them (reason on each line). `p6_page_mass_accept.txt`: rows whose mass comes from the catalog page.
6. `import_pass6.py`: writes `parts_data/harvest_2026_11_11.json` and stages data sheet page, text and photo per part; `copy_harvest_files.py` copies them into the part folders after `generate_parts.py`.
7. Every photo was checked by eye beside the CAD render (`image_cad_review.csv`); wrong photos are in `_rejected_photos/`.

`build_pass7_csv.py` + `fetch_pass5.py` fetch photos and data sheets for hand-added parts; `import_fetch_zip.py` and `accept_photos.py` bring them in.
