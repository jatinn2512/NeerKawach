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

P3 advances every 300 seconds. At each boundary it applies the previous mapped overflow, updates surface water and reserves up to 75 m³ per candidate (0.25 m³/s for 300 s). These are assumed inlet capacities. The generated rate retains enough water to fund SWMM's half-step transitions when rates change. SWMM debits each inlet's reservation by the volume it actually admits. Where candidates share a node, their contributions are debited in proportion to their available balances. Unused water returns to its original cell at the end of the simulation.

The control-free derived INP uses a 30-second rule clock so adaptive hydraulic steps land on the existing output boundaries. Hydraulic steps can be shorter. The node CSV reports instantaneous rates and integrated interval volumes separately. In the transfer CSV, `transfer_volume_m3` is the amount removed from the cell into the reservation. `native_admitted_m3`, `closing_reservation_m3` and `final_refund_m3` describe the subsequent settlement.

## Connection and overflow rules

P6 uses only the 15 existing P4 connection candidates in
`data/drainage/processed/surface_drainage_connections.geojson`. It does not
invent additional inlets or infer a new surface location from a SWMM node
depth.

P6 integrates successive node flooding rates by the trapezoidal rule over each native hydraulic step and checks their sum against SWMM's unrounded system flooding total. At a mapped node it shares the overflow among that node's candidates. The next surface step or the final state places each share in its candidate cell. Unmapped flooding leaves the coupled domain. Node depths and heads remain hydraulic diagnostics.

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

The external budget uses the native cumulative outfall flux and the measured change in surface, node and link storage. Internal capture and mapped overflow cancel across domains. The absolute volume tolerance of 0.001 m³ applies to surface accounting, exchange in each direction and the agreement between independent reconstructions. The reported gross residual must also fit the solver allowance of 1% of hydraulic inputs including initial storage. The old 30-second rectangle integration and the strict 0.001 m³ gross comparison remain available as diagnostics. [Equations, validation criteria and timestep sensitivity](../NEERKAWACH_PHASE_1_FINAL_CLOSURE.md)

## Synthetic fixture result

The 40 mm Bellandur fixture supplied 320,904 m³ of rain. The drains admitted 8,076.160 m³. SWMM flooded 4,451.300 m³, of which 2,817.714 m³ returned to mapped cells. The final surface and drainage storages were 232,745.354 and 2,412.048 m³. The gross residual was +57.446 m³ and the unrounded native continuity error was +0.711295%. Both numerical acceptance checks passed. The strict 0.001 m³ whole-domain comparison was false. [Full-precision ledger](../data/coupling/results/coupling_water_balance.json) · [Validation](../data/coupling/results/p6_validation.json)

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
