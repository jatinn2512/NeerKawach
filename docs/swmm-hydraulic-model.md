# P5 — EPA SWMM hydraulic prototype

This document covers the executable P5 hydraulic-simulation foundation for the locked Bellandur study area. It records the source boundary, explicit model assumptions, full-area rainfall allocation, hydraulic outputs, and validation artifacts. It does not claim surveyed municipal hydraulic capacity or observed flood accuracy.

## Scope and source boundary

The model is generated from the complete P4 drainage network for the canonical Bellandur area in `config/study_area.json`. P4 provides 91 nodes, 45 links, and 46 weakly connected components. The generator reads the P4 node/link GeoJSON and provenance; it does not modify P4 source data.

The hydraulic engine is EPA Storm Water Management Model (SWMM), accessed through PySWMM. References: [EPA SWMM](https://www.epa.gov/water-research/storm-water-management-model-swmm), [PySWMM Simulation API](https://pyswmm.github.io/pyswmm/reference/api/pyswmm.simulation.Simulation.html), and [PySWMM Node API](https://pyswmm.github.io/pyswmm/reference/api/pyswmm.nodes.Node.html).

## Component audit and P4 → SWMM mapping

All 31 P4 components containing valid LineString drainage links are simulated independently in one SWMM input. This represents all 76 non-orphan P4 nodes and all 45 P4 links. Components are not joined to one another; no municipal pipe, junction, or connection is fabricated.

The sole P4 outfall candidate, `drn_n_00033`, remains the only verified SWMM outfall. The other 30 linked components have no verified outfall. They retain their existing junctions and conduits and use an explicitly labelled `closed_terminal_junction` model boundary at their P4 terminal nodes. This is a hydraulic boundary assumption, not a claim about a real BBMP outfall.

The remaining 15 components are single-node terrain-inferred candidates with no P4 link. They are excluded because there is no defensible hydraulic feature to represent. Each exclusion is recorded in `data/swmm/metadata/component_assessment.json`.

`data/swmm/metadata/p4_to_swmm_mapping.json` contains an explicit record for every P4 feature:

- mapped P4 junctions → SWMM `JUNCTIONS`;
- the verified P4 outfall candidate → SWMM `OUTFALLS`;
- mapped P4 drainage links → SWMM `CONDUITS` and `XSECTIONS`;
- isolated terrain candidates → documented excluded-node records.

The mapping preserves P4 IDs, SWMM IDs, provenance, component membership, endpoints, geometry direction, and status. The one P4 link whose source direction placed the verified outfall upstream is reversed in the SWMM representation so the outfall is downstream; this is recorded as a model assumption and does not alter P4.

## Full canonical rainfall coverage

The previous one-hectare-per-node allocation represented only approximately 0.75 km², or 15.56% of the canonical area. It was therefore insufficient as the P5 rainfall input foundation.

The corrected strategy is a deterministic regular 9 × 9 grid over the exact canonical bbox from `config/study_area.json`:

- target cell size: 250 m;
- subcatchments: 81;
- cell areas: approximately 5.935–5.936 ha;
- projected canonical bbox area: 4,807,969.632 m² (4.807970 km²);
- modeled subcatchment area: 4,807,969.632 m² (4.807970 km²);
- coverage: 100.0%;
- gap area: 0 m²;
- overlap area: 0 m².

Each grid cell routes lateral runoff directly to the nearest existing simulated P4 junction by centroid distance. This is an explicit `prototype_subcatchment` allocation. It does not create a pipe, link, outfall, or verified drainage connection, and it is not an official BBMP catchment delineation. Every cell records `verified_drainage_connection: false` and `prototype_boundary_source: model_assumption` in `data/swmm/metadata/subcatchment_coverage.json`.

The independent coverage audit is stored in `data/swmm/metadata/subcatchment_coverage.json`; its GeoJSON representation is `data/swmm/metadata/subcatchments.geojson`.

## Observed values and model assumptions

Observed/source-backed inputs are P4 node coordinates, P4 DEM-sampled `ground_elevation_m`, P4 link geometry, P4 link length, source provenance, and component membership. P4 does not provide surveyed hydraulic inverts, diameters, roughness, slopes, or capacities.

The following values are therefore explicit assumptions in `config/swmm_model.json`:

- invert: `ground_elevation_m - invert_offset_below_ground_m`, with offset 1.0 m;
- circular conduit diameter: 1.0 m;
- Manning roughness: 0.013;
- zero conduit offsets and zero initial flow;
- junction maximum depth: 2.0 m, surcharge depth: 0.5 m, ponded area: 100 m²;
- closed terminal boundary for linked components without verified outfalls;
- 75% impervious area and the documented roughness/storage parameters;
- Horton infiltration;
- free, ungated boundary for the sole verified outfall.

Units are explicit in the configuration and generated input: elevations, depths, diameters, widths, offsets, ponded area, and lengths are metres or square metres as named; Manning roughness values are dimensionless; imperviousness and zero-impervious values are percentages; slope is percent; Horton rates are mm/hour; Horton decay and dry time are per hour and hours; timesteps are seconds; flow is CMS; and rainfall is mm per fixture timestep.

No single fixed runoff-coefficient parameter is used. Runoff is generated by SWMM from the configured impervious/pervious fractions, depression storage, and Horton infiltration parameters.

Assumed invert values are written only to the generated SWMM input and mapping metadata. They are never written back into P4.

## Rainfall, runoff, routing, and execution

The forcing is `data/swmm/tests/synthetic_storm.json`, explicitly labelled `source: synthetic_test`. It contains 12 five-minute records totaling 40 mm over one hour. It is not historical rainfall or an observed Bellandur event.

For the full modeled area, the geometric rainfall input is:

`0.040 m × 4,807,969.632 m² = 192,318.785 m³`.

The SWMM report prints `192,320 m³`; the 1.215 m³ difference is report display rounding, not an area-coverage deficit. The input cross-check records both values and marks the difference as report rounding. Runoff and routing continuity rows retain the displayed SWMM residuals rather than asserting a false zero balance.

Execution settings:

- flow units: CMS;
- routing: `DYNWAVE`;
- hydraulic timestep: 30 seconds;
- report timestep: 5 minutes;
- ponding: enabled;
- configured run: 2026-01-01 00:00–01:00 UTC;
- SWMM engine: 5.2.4;
- PySWMM: 2.1.0.

The run produces 836 node rows (76 nodes × 11 report times), 495 link rows (45 links × 11 report times), and 11 outfall rows.

## Maximum-node audit

The maximum extracted 5-minute report-timestep node value in the full-area run is `drn_n_00044` in `component_020`, with maximum reported depth `40.3685035 m`. PySWMM’s finer-step node statistics retain an internal peak of approximately `42.4408 m`; both values are preserved, and the acceptance headline uses the extracted report time series. The audit in `data/swmm/results/swmm_summary.json` records:

- P4 source: `government_dataset`;
- P4 ground elevation: 875.0 m;
- assumed invert: 874.0 m;
- invert source: `model_assumption`;
- configured junction maximum depth: 2.0 m;
- connected P4 link: `drn_l_00013`;
- generated link geometry: `drn_n_00045 → drn_n_00044`, approximately 337.899 m, circular 1.0 m assumed section;
- prototype cells routed to the node: 6;
- prototype area routed to the node: approximately 35.614 ha;
- routing verification: false.

The junction is configured as `874.0 2.0 0.0 0.5 100.0` in the SWMM `[JUNCTIONS]` section: assumed invert, maximum depth/surcharge threshold, initial depth, surcharge depth, and ponded area. It has no external outfall. Once the junction surcharges, the conduit can carry reverse flow back toward `drn_n_00045`, while ponding retains water in the routing system. This makes the 40.3685 m report-timestep value mathematically consistent but strongly assumption-driven. It is not a surveyed municipal hydraulic result, an observed flood depth, or a capped value.

## Water balance and diagnostics

`data/swmm/results/p5_water_balance.json` extracts the SWMM runoff and flow-routing continuity tables in cubic metres and retains PySWMM API diagnostics separately. The current full-area synthetic run reports:

- total precipitation: 192,320 m³;
- infiltration loss: 23,950 m³;
- surface runoff: 117,380 m³;
- final runoff quantity storage: 51,260 m³;
- runoff continuity error: -0.143%;
- external outflow: 14,280 m³;
- final flow-routing stored volume: 103,220 m³;
- flow-routing continuity error: 0.110%.

The report-derived displayed residuals are preserved as `computed_residual_m3_from_report_rounding`. PySWMM API diagnostics are recorded independently and are not substituted for the SWMM report accounting.

The two continuity sections are not interchangeable. Runoff Quantity Continuity is the cumulative watershed rainfall/loss accounting plus final subcatchment storage. Flow Routing Continuity is the cumulative routing inflow/outflow accounting plus initial and final routing storage. The JSON report records the exact source section, unit, cumulative versus final-state meaning, and SWMM rounding status for every volume. A positive node flooding time series does not necessarily equal routing `Flooding Loss`: with `ALLOW_PONDING YES`, water can remain as retained ponded routing storage.

Thirty linked components use the `closed_terminal_junction` boundary assumption. The per-component audit in `data/swmm/results/p5_validation.json` records component ID, boundary nodes, connected links, assigned subcatchments, maximum depth, final storage, and the reason retained storage is expected. This preserves the P4 topology without inventing real outfalls; accumulation and flooding in those components are explicitly assumption-driven.

## Outputs and reproducible commands

Generate the model, full-area subcatchments, component audit, and mapping:

```text
python scripts/data/build_swmm_model.py
```

Run SWMM through PySWMM:

```text
python scripts/data/run_swmm.py
```

Run the P5 tests:

```text
python -m unittest discover -s scripts/data -p "test_*.py"
```

Important outputs:

- `data/swmm/models/bellandur_prototype.inp` — generated SWMM model;
- `data/swmm/metadata/component_assessment.json` — 46-component audit;
- `data/swmm/metadata/p4_to_swmm_mapping.json` — complete P4 mapping/exclusion ledger;
- `data/swmm/metadata/subcatchment_coverage.json` — independent full-area coverage audit;
- `data/swmm/metadata/subcatchments.geojson` — full-area subcatchment geometries;
- `data/swmm/results/node_timeseries.csv`;
- `data/swmm/results/link_timeseries.csv`;
- `data/swmm/results/outfall_timeseries.csv`;
- `data/swmm/results/component_summary.json`;
- `data/swmm/results/p5_water_balance.json`;
- `data/swmm/results/swmm_summary.json`;
- `data/swmm/results/p5_validation.json`;
- `data/swmm/results/preview/p5_network_qa.geojson`;
- `data/swmm/results/preview/p5_simulation_qa.geojson`;
- `data/swmm/results/preview/p5_subcatchments_qa.geojson`.

## Validation and limitations

The P5 tests check full canonical subcatchment coverage, no material gaps or overlaps, agreement between coverage metadata and the generated SWMM model, complete P4 mapping, component preservation, boundary validity, deterministic model generation and runtime signatures, simulation startup/completion, output coverage, finite/non-negative hydraulic values, rainfall-volume reconciliation, and maximum-node provenance.

The model remains a prototype. Hydraulic parameters, closed boundaries, and full-area nearest-junction subcatchment routing are assumptions. The P4 network does not provide surveyed underground hydraulic attributes, and the rainfall fixture is synthetic. No official municipal catchment delineation, observed flood validation, or surveyed capacity claim is made.
