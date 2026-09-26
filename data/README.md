# Neer Kawach data layout

P1 data is partitioned by source and by processing state:

- `dem/raw/` preserves the downloaded SRTM HGT tile; `dem/metadata/` records its source and inspection metadata.
- `roads/raw/` preserves the Overpass response; `roads/processed/` contains bbox-clipped GraphML and GeoJSON.
- `rainfall/raw/<provider>/` preserves native provider files; `rainfall/processed/` contains the provider-neutral rainfall records; `rainfall/metadata/` contains source catalogs and sidecars.
- `surface_routing/input/` contains projected P3 working rasters; `surface_routing/results/` contains synthetic-test depth time series and QA reports; `surface_routing/tests/` contains clearly labeled deterministic fixtures.

All spatial data in the P1 foundation uses the canonical extent in `config/study_area.json` and EPSG:4326. Run `python scripts/validate_p1.py` from the repository root before handing data to P2.
