# P7 Flood Inundation Mapping & Street-Level Impact

## Scope

P7 is a downstream product-generation phase. It reads the validated P6
coupled surface-depth rasters, P6 water-balance reports, the canonical
Bellandur study area, and the existing OSM road GeoJSON. It does not rerun or
modify P1–P6 models, rainfall forcing, drainage coupling, or SWMM.

## Source and spatial conventions

The source of truth is the P6 timestamped depth series in
`data/coupling/results/coupled_surface_depth/`. The source rasters use
EPSG:32643 and 30 m cells. P7 retains that CRS and grid for raster outputs.
Vector extents and road impacts are exported as EPSG:4326 GeoJSON, matching
the existing P1 road convention.

The canonical bbox is loaded only from `config/study_area.json`. P7 masks each
source raster to pixels whose centers fall inside that bbox; pixels outside
the mask are written as nodata. No raster resampling or unsupported precision
is introduced.

## Inundation threshold and risk classes

The configured inundation threshold is **0.05 m**. A cell is inundated when
its P6 depth is at least that value. This is a project-defined visualization
and decision threshold, not a scientific, regulatory, or safety standard.

The deterministic project-defined maximum-depth classes are:

| Code | Class | Depth |
|---:|---|---:|
| 0 | none | `< 0.05 m` |
| 1 | shallow | `0.05–<0.15 m` |
| 2 | moderate | `0.15–<0.30 m` |
| 3 | deep | `>= 0.30 m` |

These thresholds are configured in `config/inundation.json` and should not be
presented as an authoritative flood-risk standard.

## Flood extent and time series

For every P6 timestamp, P7 writes a masked depth GeoTIFF and a GeoJSON extent
containing polygons for connected inundated cell groups. It also writes a
maximum depth raster, maximum extent, and maximum-depth risk-class raster.
Timestamps are copied from P6 raster tags. The P6 post-storm snapshot is
retained as a timestamped state; it is not treated as an additional rainfall
interval.

`inundation_timeseries.csv` records instantaneous inundated area, cell count,
maximum depth, threshold, risk class, and source raster for every state.
Areas are cell-count times the source 30 m cell area and are therefore raster
approximations, not surveyed polygon areas.

## Road impacts

P7 uses the existing clipped OSM road geometries in
`data/roads/processed/bellandur_roads.geojson`. Each line is transformed to
the P6 raster CRS and rasterized with `all_touched=True`. The maximum depth of
the touched P6 cells is reported for each road segment and timestamp.

Per-road outputs include:

- affected status at the configured threshold;
- maximum intersecting depth;
- first inundation timestamp;
- peak inundation timestamp;
- duration above threshold;
- project-defined peak risk class;
- projected road length.

Duration is the sum of intervals to the next P6 timestamp for states above the
threshold. The final post-storm snapshot has no following interval and adds no
duration. Road elevations are not used or invented, and the result is a
surface-depth intersection indicator rather than a vehicle passability claim.

## Provenance and P6 inherited metrics

Every raster is tagged with source phase, source raster, timestamp, CRS, units,
threshold, and mask method. GeoJSON properties and CSV rows retain source
phase and threshold fields. `data/inundation/metadata/p7_provenance.json`
records the full source-file list, study area, CRS, units, threshold, and
output list.

`p7_summary.json` carries P6 totals without recomputing them: surface-to-
drainage transfer, mapped return, unmapped overflow, final surface storage,
final drainage storage, and the P6 unexplained residual. These are explicitly
marked as inherited P6 balance values.

## Reproducible command

From the repository root:

```powershell
python scripts/data/generate_inundation.py
python -m unittest scripts.data.test_inundation
```

The P7 generator is offline and has no live-service dependency. Generated
products are placed under `data/inundation/`; the directory is ignored as
generated data while the configuration, script, tests, and documentation are
tracked.

## Limitations

- P7 inherits P6's synthetic rainfall and prototype hydraulic assumptions.
- P4 connections remain terrain-inferred candidates and are not surveyed
  inlets.
- Flood depth is modeled surface water, not a flood observation or ground-
  truth measurement.
- OSM road geometry has no invented road elevation and does not establish
  vehicle safety or passability.
- The risk classes and 0.05 m threshold are project-defined display/decision
  categories.
- No P8 routing or public-facing API integration is included.
