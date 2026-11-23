# P3 — Dynamic surface-water routing

P3 is a prototype, time-stepped surface-water-routing foundation for the locked Bellandur study area. It is not a calibrated 2D hydrodynamic urban-flood model, a historical nowcast, or a substitute for SWMM/drainage modelling.

## Inputs and working CRS

The runner reads the canonical study-area definition from [`config/study_area.json`](../config/study_area.json) and uses the buffered P2 DEM as the primary terrain input:

- `data/dem/processed/bellandur_dem_buffered.tif`
- `data/dem/terrain/slope.tif`
- `data/dem/terrain/aspect.tif`
- `data/dem/terrain/flow_direction.tif`
- `data/dem/terrain/flow_accumulation.tif`
- `data/dem/terrain/depressions.tif`

The P2 inputs are checked for matching EPSG:4326 CRS, dimensions and affine transform before any reprojection.

Physical calculations use EPSG:32643, WGS 84 / UTM zone 43N. Bengaluru is near 77.65°E, which places Bellandur in UTM zone 43N. This local projected CRS provides metre-based distances and square-metre cell areas without changing the canonical EPSG:4326 study-area definition. The transformation uses rasterio/GDAL reprojection; the original P1/P2 rasters remain unchanged.

The working grid has 95 columns and 97 rows of 30 m cells in EPSG:32643. Bilinear reprojection writes the DEM as Float32. Other terrain layers use nearest-neighbour resampling. [Working grid metadata](../data/surface_routing/input/working_grid.json)

## Rainfall interface

The routing engine accepts provider-neutral rainfall forcing rather than referring to IMD, DWR, IMERG, or any other provider in its model equations.

Supported inputs:

- JSON forcing with `source`, `timestep_seconds`, `units: "mm"`, and timestamped `rainfall_mm` records. Uniform JSON forcing is used by the deterministic fixture.
- P1 normalized CSV with `timestamp, latitude, longitude, rainfall_mm, source`; a timestep must be supplied to the runner. Points are transformed to the working grid and aggregated by cell/time.

The default fixture is [`data/surface_routing/tests/synthetic_rainfall.json`](../data/surface_routing/tests/synthetic_rainfall.json). It is explicitly labeled `source = synthetic_test` and is not observed rainfall, IMD rainfall, DWR/QPE, IMERG, or a historical Bellandur storm. The currently acquired P1 IMD/NCMRWF product is daily and 0.25°, so it is not used to claim sub-hourly nowcasting.

## Historical MOSDAC replay

From the repository root, run the P3 engine on the published Task 2.4 event with the data-processing Python environment.

```powershell
python -B scripts/data/run_surface_routing.py --temporal-manifest data/rainfall/temporal/068d3d77a49c5602/manifest.json --event bellandur_2022-09-01
```

The same manifest contains the alternative event `bellandur_2022-08-31`. Each invocation creates a new `data/runs/<run-id>/manifest.json` and writes its products in the neighbouring `results/` directory. The historical path reads the existing projected terrain and flow direction. Running the CLI without historical arguments selects the existing synthetic fixture and its normal output location.

The adapter verifies the selected event, its checksummed temporal and spatial products, source labels and native pixels before starting P3. Each band holds allocated depth in mm for one 300-second interval. The adapter divides by 1,000 once to supply Float64 metres. A valid dry cell stays zero. P3 requires finite inputs everywhere, so the adapter represents an excluded terrain cell with the finite sentinel −1 outside the valid mask. The engine clears excluded cells before any rainfall arithmetic. A source-coverage gap on valid terrain stops the run.

Each input band has a relative start and end in seconds. A saved state and its `TIMESTAMP` tag identify the **end** of that step. The summary links each state to its original source label. Absolute UTC bounds for the underlying MOSDAC rainfall intervals are unknown.

The pre-run rainfall check integrates the mm bands with the spatial product's covered area. P3 calculates a second total from its metre inputs and grid-cell area. The per-step and total comparisons use an absolute tolerance of 1e−7 m³. The model's gross balance has its own configured tolerance of 1e−6 m³. The manifest records both checks, the configuration's SHA-256 version, the input bands and files, and the checksums of the outputs. The native rainfall resolution is approximately 4 km. Each of the six five-minute allocations within a nominal half-hour has the same intensity.

## Runoff formulation

Parameters are explicit in [`config/surface_routing.json`](../config/surface_routing.json):

- timestep: 300 s;
- runoff coefficient: 0.75;
- infiltration/loss rate: 0.5 mm/hour;
- initial depth: 0 m;
- routing timescale: 600 s;
- D8 preference factor: 1.25;
- boundary condition: closed;
- mass-balance tolerance: 1e-6 m³.

For each cell and timestep:

```text
rainfall depth [m] = rainfall [mm] / 1000
effective runoff [m] = rainfall depth × runoff coefficient
immediate coefficient loss [m] = rainfall depth − effective runoff
infiltration loss [m] = min(effective runoff, infiltration rate × timestep)
surface input [m] = effective runoff − infiltration loss
```

Depth is converted to volume with `volume = depth × cell_area_m2`. The projected 30 m grid has 900 m² cells.

## Dynamic water movement

At every timestep, the current water-surface head is:

```text
head = DEM elevation + current water depth
```

Each unique neighbouring cell pair is evaluated in the eight-neighbourhood. Water moves only from higher current head to lower current head. Potential exchange is proportional to head difference, cell area, and an explicit exchange fraction `min(0.5, timestep / routing_timescale)`. Transfers are calculated conservatively and scaled per source cell so total outflow cannot exceed the source cell's available water volume.

The reprojected D8 direction provides a 1.25 preference multiplier when a pair agrees with the static downslope direction, but water is not permanently routed along D8. Current water depth/head controls movement, allowing water to pool and redistribute in depressions.

Boundary behavior is explicit:

- `closed`: no water leaves the raster boundary; used by the deterministic demonstration run.
- `open`: each boundary cell releases the configured fraction of its current volume per timestep and the released volume is recorded as boundary outflow.

No drainage network, sewer connection, runoff coupling, or surface-to-drainage exchange is implemented.

## Numerical stability and mass balance

The exchange fraction is timestep-limited and every transfer is capped by available source volume. Depths are constrained to be non-negative. Redistribution is conservative; boundary outflow and modeled losses are tracked separately.

The accounting is reported in three linked stages so that no volume is counted twice or omitted:

```text
rainfall input = effective runoff input + coefficient loss
effective runoff input = surface-water input + infiltration loss
modeled losses = coefficient loss + infiltration loss

initial storage + surface-water input − boundary outflow = final storage
initial storage + rainfall input − coefficient loss − infiltration loss
  − boundary outflow = final storage
```

Internal neighbour transfers are not sources or sinks; they only redistribute water between cells and therefore cancel from the balance. The simulation checks the routing-only residual, the surface-input balance, and the gross rainfall balance at every step and raises a validation error if any exceeds the configured tolerance. `runoff_input_m3` is the effective runoff before infiltration, while `surface_water_input_m3` is what actually enters routing.

The previous report appeared difficult to reconcile because it displayed effective runoff before infiltration alongside aggregate modeled losses that included both coefficient loss and infiltration loss. The implementation was already conservative; the report now exposes both loss components and both equivalent balance equations.

## Outputs

The reusable runner is [`scripts/data/run_surface_routing.py`](../scripts/data/run_surface_routing.py), with core numerical logic in [`scripts/data/surface_routing_core.py`](../scripts/data/surface_routing_core.py).

- Projected working rasters: `data/surface_routing/input/`
- Per-timestep depth GeoTIFFs: `data/surface_routing/results/depth/`
- Maximum depth: [`data/surface_routing/results/max_depth.tif`](../data/surface_routing/results/max_depth.tif)
- Summary: [`data/surface_routing/results/summary.json`](../data/surface_routing/results/summary.json)
- QA report: [`data/surface_routing/results/p3_validation.json`](../data/surface_routing/results/p3_validation.json)
- Lightweight PGM inspection previews: `data/surface_routing/results/preview/`

The corrected synthetic fixture supplies 320,904 m³ of rainfall, of which 80,226 m³ is coefficient loss and 2,674.2 m³ is infiltration. Final surface storage is 238,003.8 m³. The closed boundary has zero outflow and the gross residual is below 0.000001 m³. Maximum depth is 1.30278 m. [Phase 1 verification](../NEERKAWACH_PHASE_1_REPORT.md)

## Tests

Run:

```powershell
python -m unittest discover -s scripts/data -p "test_*.py" -v
```

The test suite covers no-rain behavior, uniform-rain generation, slope movement, bowl accumulation, open-boundary outflow, component-level mass conservation with losses, non-negative depth, determinism, and projected raster consistency. The current run passes all 9 tests.

## Limitations and next phase

This is a lightweight raster prototype with simplified exchange physics, no calibrated roughness, no infiltration spatial variability, no rainfall downscaling, no observed sub-hourly forcing, and no drainage coupling. Static terrain derivatives are inputs, not a flood simulation by themselves. Synthetic forcing must not be presented as an observation-backed nowcast.

The exact next phase is P4 — Drainage Network Foundation.
