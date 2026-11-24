# P3 — Dynamic surface-water routing

P3 is a prototype, time-stepped surface-water-routing foundation for the locked Bellandur study area. It is not a calibrated 2D hydrodynamic urban-flood model, a historical nowcast, or a substitute for SWMM/drainage modelling.

## Inputs and working CRS

The runner reads the canonical study-area definition from [`config/study_area.json`](../config/study_area.json) and uses the buffered P2 DEM as the primary terrain input:

- `data/dem/processed/bellandur_dem_buffered.tif`
- `data/dem/terrain/slope.tif`
- `data/dem/terrain/aspect.tif`

The P2 inputs are checked for matching EPSG:4326 CRS, dimensions and affine transform before any reprojection.

Physical calculations use EPSG:32643, WGS 84 / UTM zone 43N. Bengaluru is near 77.65°E, which places Bellandur in UTM zone 43N. This local projected CRS provides metre-based distances and square-metre cell areas without changing the canonical EPSG:4326 study-area definition. The transformation uses rasterio/GDAL reprojection; the original P1/P2 rasters remain unchanged.

The working grid has 95 columns and 97 rows of 30 m cells in EPSG:32643. Bilinear reprojection writes the DEM as Float32. Slope and aspect use nearest-neighbour resampling. P3 version 1.3 derives its D8 preference raster from the elevations and valid mask of that projected DEM. It also writes contributing-cell counts, contributing areas, sink classes, flat regions and provisional terminal IDs. The summary and run manifest record the DEM and direction checksums, affine, CRS and algorithm version. [Terrain methods and interpretation](terrain-processing.md#projected-terrain-for-p3)

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

The same manifest contains the alternative event `bellandur_2022-08-31`. Each historical invocation uses the projected DEM identified by the published rainfall bundle and derives directions in `data/runs/<run-id>/terrain/`. Depth frames and the summary go in the neighbouring `results/` directory. Running the CLI without arguments selects the synthetic fixture and prepares its working grid in its own run directory.

The adapter verifies the selected event, its checksummed temporal and spatial products, source labels and native pixels before starting P3. Each band holds allocated depth in mm for one 300-second interval. The adapter divides by 1,000 once to supply Float64 metres. A valid dry cell stays zero. P3 requires finite inputs everywhere, so the adapter represents an excluded terrain cell with the finite sentinel −1 outside the valid mask. The engine clears excluded cells before any rainfall arithmetic. A source-coverage gap on valid terrain stops the run.

Each input band has a relative start and end in seconds. A saved state and its `TIMESTAMP` tag identify the **end** of that step. The summary links each state to its original source label. Absolute UTC bounds for the underlying MOSDAC rainfall intervals are unknown.

The pre-run rainfall check integrates the mm bands with the spatial product's covered area. P3 calculates a second total from its metre inputs and grid-cell area. The per-step and total comparisons use an absolute tolerance of 1e−7 m³. The model's gross balance has its own configured tolerance of 1e−6 m³. The manifest records both checks, the configuration's SHA-256 version, the input bands and files, and the checksums of the outputs. The native rainfall resolution is approximately 4 km. Each of the six five-minute allocations within a nominal half-hour has the same intensity.

## Uniform fixture runoff formulation

The default invocation retains the uniform engineering fixture. Pass a prepared manifest with `--surface-parameters` to use sub-cell land-cover fractions and topsoil capacity scenarios for either synthetic or historical rainfall. Each run records its active parameterization. [Spatial runoff equations, source inventory and Bellandur regressions](spatial-runoff.md)

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

P3 version 1.2 integrates a head-driven graph diffusion over the eight valid neighbours. For cell area (A) in m², centre distance (d) in m, routing timescale (T) in seconds and internal step (s) in seconds, the proposed exchange depth is `(s/T) × (A/d²) × p × |head difference|` metres. Moving this depth between two equal-area cells transfers the same volume at both ends. The donor is the cell with greater head. The dimensionless D8 factor `p` is 1.25 in its preferred direction and 1 elsewhere. On the square working grid an axial edge has twice the geometric weight of a diagonal edge.

The earlier implementation calculated all eight transfers from one head field and limited only the donor's total volume. Several neighbours could each supply a large fraction of the same receiver's head deficit. In a closed basin the receiver could overfill, then empty on the next step. The global volume balance could still close.

The corrected method sums the incident weights `(A/d²) × p` at **both** endpoints, using the larger of each edge's two possible directional weights. If the largest sum on the grid is `D`, one forcing interval uses `N = max(1, ceil(2 × Δt × D / T))` equal hydraulic substeps. Every donor in each substep divides its available water proportionally among its requested transfers when those requests exceed storage. Both endpoints use the same limited edge transfer. Water heads and flow directions are updated for the next substep. Rain and the configured boundary rule are applied once per forcing interval.

Boundary behavior is explicit:

- `closed`: no water leaves the raster boundary; used by the deterministic demonstration run.
- `open`: each boundary cell releases the configured fraction of its current volume per timestep and the released volume is recorded as boundary outflow.

No drainage network, sewer connection, runoff coupling, or surface-to-drainage exchange is implemented.

## Numerical stability and mass balance

The total incident exchange coefficient is at most one half at each cell, including receivers with several donors. Availability limiting can only reduce it. Each updated head is a convex combination of the local head and its neighbours, with at least half the weight retained locally. The symmetric exchange matrix for each realized substep has eigenvalues in [0, 1]. This damps the alternating mode while allowing a wet front to advance or a local depth to change direction as its neighbours drain. The substep count follows from the graph and the existing routing timescale. Dry cells supply zero water. Terrain NoData cells have no exchange edges.

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

- The `input/` directory in each synthetic run contains the working DEM and derived terrain. The `terrain/` directory in each historical run contains the derived terrain.
- The `results/depth/` directory contains one GeoTIFF per saved timestep.
- Since version 1.2, `max_depth.tif` and its preview contain the greatest saved depth **at each cell**. Cells can peak at different times. The GeoTIFF carries `STATISTIC=cellwise_maximum_over_saved_timesteps`, metres and the terrain mask.
- The summary records the Float64 domain-wide peak, its first step index and its timestamp. `domain_peak_depth_file` identifies the complete timestamped depth raster at that instant. Float32 output can round nearby peaks to the same saved value.
- The `results/` directory also holds `summary.json`, `p3_validation.json`, and the `preview/` directory of PGM images.

For a fresh 40 mm synthetic fixture, run `python -B scripts/data/run_surface_routing.py`. The existing `--run-scoped` flag also works. Each execution writes under a new `data/runs/<run-id>/`. Published Phase 1 and Phase 2 products remain available at their original fixed paths.

On the Bellandur fixture the version 1.3 peak is 1.62810 m, compared with 1.63014 m in version 1.2. Rainfall is 320,904 m³, coefficient loss 80,226 m³, infiltration 2,674.2 m³, boundary outflow zero and final surface storage 238,003.8 m³. The version 1.3 historical replay peaks at 0.253389 m at the end of relative hour 19. Earlier P3 manifests identify version 1.1 in their result summaries. Their `max_depth.tif` is a single domain-peak snapshot, and the Phase 1 synthetic scalar peak was 1.30278 m.

## Tests

Run:

```powershell
python -B -m pytest -q scripts/data/test_working_terrain.py scripts/data/test_surface_routing.py scripts/data/test_historical_p3_rainfall.py scripts/data/test_dem_registration.py scripts/data/test_water_budget.py
```

The P3 tests cover equilibrium, dry recession, simultaneous donors, shallow films, directional transfer, mass conservation and timestep refinement against the exact two-cell relaxation. The historical and synthetic runner regressions independently reduce the saved depth rasters and compare their maxima, masks and peak frames.

## Limitations and next phase

This is a lightweight raster prototype with simplified exchange physics. Spatial mode uses provisional topsoil estimates on mapped pervious fractions. Local roughness, event moisture, surface-to-drain exchange and sub-hourly rainfall variability remain unresolved. Synthetic forcing is an engineering fixture.

The exact next phase is P4 — Drainage Network Foundation.
