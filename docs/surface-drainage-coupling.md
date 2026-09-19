# P6 Surface-Water ↔ Drainage Coupling

## Scope

P6 couples the existing P3 surface-routing prototype to the existing P4/P5
drainage foundation for the Bellandur study area. It is a synthetic-fixture
coupling run only. It does not implement surface routing, SWMM model
construction, road routing, flood-depth validation, or a production API.

The canonical study area remains defined only by
`config/study_area.json`. The P3 working surface grid is the existing projected
30 m grid in EPSG:32643 and includes its existing processing buffer. P6 does
not silently replace that grid with the canonical bbox.

## Coupling architecture

P3 owns rainfall and surface excess generation. The derived P6 SWMM input is
created from the preserved P5 model with:

- the `SyntheticStorm` rainfall values set to zero;
- `ALLOW_PONDING NO`, so SWMM node flooding is an explicit overflow signal;
- P3 surface excess injected as generated lateral inflow at existing P4/P5
  drainage nodes.

This prevents rainfall from being counted once in P3 and again in the SWMM
subcatchments. The original P5 model is not modified.

The exchange order is deterministic:

1. return the previous exchange's mapped SWMM overflow to its existing P4
   surface cell;
2. run the P3 surface step;
3. transfer available water at existing P4 connection candidates to SWMM;
4. advance SWMM at its 30-second hydraulic timestep until the next 300-second
   exchange.

The P3/P6 exchange interval is 300 seconds. The P5 hydraulic timestep remains
30 seconds. Surface-to-drainage transfer is bounded by:

```text
transfer = min(available surface volume, 0.25 m3/s * 300 s)
```

The 0.25 m³/s per-connection capacity is a documented prototype model
assumption, not a surveyed municipal capacity.

## Connection and overflow rules

P6 uses only the 15 existing P4 connection candidates in
`data/drainage/processed/surface_drainage_connections.geojson`. It does not
invent additional inlets or infer a new surface location from a SWMM node
depth.

SWMM flooding is integrated from the extracted node flooding rate at each
30-second step. If a flooding node has an existing P4 connection candidate,
the corresponding volume is returned to that candidate's P3 cell. If it has no
candidate, the volume is recorded in the overflow CSV as an explicitly
unmapped drainage-domain sink. Node depth/head remain hydraulic diagnostics;
they are not converted directly to surface depth.

The P4 candidate provenance remains `terrain_inferred` and
`candidate_only_no_transfer_simulated`. Transfer capacity remains
`model_assumption` provenance.

## Mass-balance accounting

The P3 surface balance is:

```text
initial surface storage
+ rainfall input
- coefficient loss
- infiltration loss
- boundary outflow
- surface-to-drainage transfer
+ mapped drainage-to-surface return
= final surface storage
+ surface residual
```

The extracted drainage balance is:

```text
generated lateral inflow
- external outfall discharge
- SWMM node flooding
- final node/link routing storage
= hydraulic continuity residual
```

The coupled balance combines those domains. Mapped flooding is a source back
to P3; unmapped flooding remains a named drainage-domain sink. The validation
also checks:

```text
SWMM flooding = mapped return + unmapped flooding
```

The report and the extracted time series are not interchangeable accounting
sources. SWMM report values are rounded display totals and the report's
continuity error is nonzero. P6 therefore uses the extracted 30-second
node/link time series for the drainage-domain totals, while retaining report
values as diagnostics. The synthetic run records a 57.6773 m³ hydraulic
continuity residual and classifies it explicitly as the SWMM numerical
continuity bucket. The unexplained coupled residual after that explicit bucket
is approximately zero and is the value subject to the configured 0.001 m³
tolerance.

The corrected accounting also treats direct generated inflow at the SWMM
outfall node as boundary discharge. Measuring only its connecting conduit
would under-count the external outflow.

## Synthetic fixture result

The deterministic P3 fixture contains 40 mm over 12 five-minute records. The
P3 buffered surface domain receives 314,100 m³ of rainfall input. The P6 run
transfers 8,928.4424 m³ to drainage, returns 3,188.4006 m³ from mapped
overflow, records 1,846.3115 m³ as unmapped overflow, and leaves 227,217.4581
m³ in the surface domain plus 2,555.8338 m³ in final SWMM routing storage.

The maximum coupled surface depth in the fixture is 1.85147 m. The maximum
coupled SWMM node depth is 2.5 m at `drn_n_00021`; it is a drainage-node
diagnostic, not a street-water depth. The original P5 baseline's reported
40.3685 m maximum at `drn_n_00044` remains assumption-driven and is not
reinterpreted by P6.

## Files

Configuration and script:

- `config/coupling_model.json`
- `scripts/data/run_coupling.py`
- `scripts/data/test_coupling.py`

Derived input and outputs:

- `data/coupling/input/bellandur_coupled_zero_rain.inp`
- `data/coupling/results/surface_to_swmm_timeseries.csv`
- `data/coupling/results/swmm_to_surface_timeseries.csv`
- `data/coupling/results/swmm_node_timeseries.csv`
- `data/coupling/results/swmm_link_timeseries.csv`
- `data/coupling/results/coupled_surface_depth/`
- `data/coupling/results/coupled_max_depth.tif`
- `data/coupling/results/coupling_summary.json`
- `data/coupling/results/coupling_water_balance.json`
- `data/coupling/results/p6_validation.json`
- `data/coupling/metadata/coupling_connections.json`
- `data/coupling/preview/`

The preserved P3, P4, and P5 source products remain in their original
directories. P6 output is reproducible by running:

```powershell
& 'C:\Users\jxtro\AppData\Local\Programs\Python\Python313\python.exe' scripts/data/run_coupling.py
```

## Limitations

- The rainfall fixture is synthetic, not an observed event.
- P4 surface-drainage connections are terrain-inferred candidates, not
  surveyed inlet locations.
- The transfer capacity is a configurable model assumption.
- P5 contains assumption-driven elevations, conduit sizes, roughness, ponded
  areas, and closed-terminal boundaries; P6 preserves those provenance flags.
- Unmapped SWMM flooding is recorded but not assigned a fabricated surface
  location.
- No claim is made that the prototype depths or routing outputs represent
  validated street-level flood conditions.
