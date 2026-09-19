# P2 — DEM preparation foundation

This document covers P2 DEM preparation and the terrain-derivative stage: converting the preserved SRTM HGT source into GeoTIFF, preparing a buffered working raster, clipping to the locked Bellandur bbox, deriving static terrain indicators, and validating the outputs. It does not implement dynamic water movement, sink filling, runoff, flood depth, flood extent, or routing.

## Inputs and source

- Canonical study-area config: [`config/study_area.json`](../config/study_area.json)
- Raw DEM: [`data/dem/raw/N12E077.hgt.gz`](../data/dem/raw/N12E077.hgt.gz)
- P1 source metadata: [`data/dem/metadata/srtm_n12e077.json`](../data/dem/metadata/srtm_n12e077.json)
- Source: NASA/USGS SRTMGL1.003 via the public AWS Terrain Tiles URL recorded in the metadata
- Native HGT: 3601 × 3601 big-endian signed 16-bit elevation postings, nodata `-32768`, EPSG:4326, 1 arc-second posting interval

The raw compressed file is read but never modified. The script checks its expected dimensions, byte count, CRS, tile coverage and P1 metadata before writing outputs.

## Processing choices

The working buffer is 300 m around the canonical bbox. This is approximately ten native 30 m cells, enough to provide near-boundary context for later terrain operations without expanding the prototype area excessively. The requested geographic buffer is converted to latitude/longitude using the study-area mid-latitude, then aligned outward to the native 1 arc-second grid.

The canonical bbox is read directly from `config/study_area.json`:

```text
min_lat 12.925
min_lon 77.650
max_lat 12.945
max_lon 77.670
```

The source values are copied into GeoTIFFs at the native posting interval. No reprojection, resampling, interpolation, or elevation modification is performed. The final clipped raster is exactly 72 × 72 pixels with exact bounds `77.650, 12.925, 77.670, 12.945` and a 1 arc-second transform.

## Outputs

- [`data/dem/processed/bellandur_dem_source.tif`](../data/dem/processed/bellandur_dem_source.tif): full 1° source tile converted to GeoTIFF; 3601 × 3601.
- [`data/dem/processed/bellandur_dem_buffered.tif`](../data/dem/processed/bellandur_dem_buffered.tif): native-grid 300 m buffered working raster; 92 × 92; aligned extent approximately `77.647222, 12.922222, 77.672778, 12.947778`.
- [`data/dem/processed/bellandur_dem_clipped.tif`](../data/dem/processed/bellandur_dem_clipped.tif): exact canonical Bellandur raster; 72 × 72; extent `77.650000, 12.925000, 77.670000, 12.945000`.
- [`data/dem/metadata/bellandur_dem_processed.json`](../data/dem/metadata/bellandur_dem_processed.json): processing metadata and validation report.

All prepared rasters use EPSG:4326, signed 16-bit elevation values, nodata `-32768`, and a pixel interval of `0.0002777777777777778°`. At Bellandur latitude this is approximately 30.14 m east-west by 30.92 m north-south; the source is commonly described as approximately 30 m SRTM resolution.

## Reproduction

The processing script is [`scripts/data/process_dem.py`](../scripts/data/process_dem.py). Its isolated dependency is [`scripts/requirements-data.txt`](../scripts/requirements-data.txt); it is separate from the backend runtime requirements.

```powershell
python -m pip install -r scripts/requirements-data.txt
python scripts/data/process_dem.py
```

The script is safe to rerun and accepts `--buffer-m <metres>` for an explicit alternative buffer. It always reads the canonical bbox from `config/study_area.json` and writes the validation report after all checks pass.

## Validation performed

The report verifies:

- GeoTIFF CRS is EPSG:4326.
- Raster dimensions and transform are present.
- Pixel size matches the 1 arc-second source interval.
- Buffered and clipped rasters cover the canonical bbox.
- The clipped extent is exactly the canonical bbox after grid alignment.
- Nodata is preserved as `-32768`.
- Minimum and maximum elevation are computed from valid pixels.
- Valid-pixel count and nodata-pixel count are recorded.
- The final clipped raster has no empty pixels.
- The original compressed HGT remains present.

The clipped DEM elevation range is 869–899 m, with 5,184 valid pixels and no nodata pixels. This is a preparation-quality check only; it is not a claim about flood-model accuracy or terrain-model accuracy.

## Limitations and boundary for the next phase

SRTM is a regional elevation product rather than a surveyed urban drainage surface. The prepared raster remains in geographic coordinates and uses the source elevation postings without vertical-datum adjustment. Later terrain processing should make any projected working-CRS or vertical-reference choice explicit before deriving terrain products.

## Terrain derivatives

The derivative script is [`scripts/data/derive_terrain.py`](../scripts/data/derive_terrain.py). It uses the buffered DEM [`data/dem/processed/bellandur_dem_buffered.tif`](../data/dem/processed/bellandur_dem_buffered.tif), never the clipped 72 × 72 DEM as its primary input. The buffered source is validated before processing and its SHA-256 hash is checked again after processing.

The data-processing stack is isolated in [`scripts/requirements-data.txt`](../scripts/requirements-data.txt): rasterio for GeoTIFF I/O/georeferencing and NumPy for array calculations. Backend dependencies remain unchanged.

### Slope

Output: [`data/dem/terrain/slope.tif`](../data/dem/terrain/slope.tif)

Slope uses a Horn 3×3 finite-difference gradient. Geographic pixel spacing is converted to local metres using the raster mid-latitude, then slope is calculated as `atan(sqrt(dzdx² + dzdy²))` in degrees. The valid range is 0–90 degrees. Cells without a complete valid 3×3 neighbourhood, including the one-cell raster border, use float nodata `-9999`.

### Aspect

Output: [`data/dem/terrain/aspect.tif`](../data/dem/terrain/aspect.tif)

Aspect is the azimuth of the downslope vector, expressed in degrees clockwise from north, with values in `[0, 360)`. Flat cells have no defined direction and use float nodata `-9999`. The same Horn gradient and valid-neighbourhood rule as slope is used.

### Flow direction

Output: [`data/dem/terrain/flow_direction.tif`](../data/dem/terrain/flow_direction.tif)

Flow direction uses a deterministic D8 steepest-positive-descent method. Candidate neighbours are ranked by elevation drop divided by physical neighbour distance; diagonal neighbours therefore use diagonal distance. The encoding is ESRI-style:

```text
E=1, SE=2, S=4, SW=8, W=16, NW=32, N=64, NE=128
0 = no positive descent / raw sink
-9999 = input nodata
```

This is a terrain-derived downslope indication, not a complete urban hydraulic model. Raster-edge cells only consider neighbours inside the buffered raster.

### Flow accumulation

Output: [`data/dem/terrain/flow_accumulation.tif`](../data/dem/terrain/flow_accumulation.tif)

Accumulation uses the generated D8 directions and a topological graph traversal. Each valid cell starts with a contribution of one, so each output value is the number of valid DEM cells contributing to that cell, including itself. It is not converted to runoff, discharge, flood depth, or flood extent. Float nodata is `-9999`.

### Depressions and low points

Outputs:

- [`data/dem/terrain/depressions.tif`](../data/dem/terrain/depressions.tif)
- [`data/dem/terrain/low_points.geojson`](../data/dem/terrain/low_points.geojson)

No filling or alteration of the DEM is performed. Cells with raw D8 code `0` are classified as:

```text
0 = non-sink
1 = local minimum
2 = flat/tied sink
3 = boundary sink
255 = nodata
```

The GeoJSON contains the raw sink cells with elevation and classification properties. These are screening candidates only: the method cannot distinguish natural depressions, DEM artefacts, flat quantization effects, buildings, culverts, or engineered urban drainage. The low-point layer is retained on the full buffered grid, not cropped to the canonical bbox.

## Derivative QA and metadata

The machine-readable report is [`data/dem/metadata/terrain_derivatives.json`](../data/dem/metadata/terrain_derivatives.json). It records source DEM hash, CRS, transform, resolution, extents, nodata, algorithms, output ranges and validation results.

All derivative rasters preserve the source DEM's EPSG:4326 CRS, 92 × 92 dimensions, transform and 1-arc-second pixel spacing. Validation confirmed:

- source buffered DEM unchanged;
- CRS and transform alignment across every raster;
- valid D8 codes only;
- slope range 0–15.802 degrees;
- aspect range 0–358.633 degrees for defined aspects;
- flow accumulation range 1–67 contributing cells;
- depression codes restricted to 0–3 with nodata 255;
- 8,464 valid cells for flow direction, accumulation and depression outputs;
- no unexpected empty cells in those outputs.

Slope and aspect intentionally contain nodata on the 364-cell outer kernel border, plus undefined flat aspects. No preview PNGs were created because the requested GIS-ready rasters and GeoJSON are sufficient for this small processing stage.

The exact next step is P3 — Dynamic Surface-Water Routing, using these products as static terrain inputs. That phase must separately define how raw sinks, accumulation thresholds, rainfall and urban drainage constraints are handled.
