# P4 — Bellandur drainage-network foundation

P4 establishes a directed drainage graph and surface-association candidates for
the canonical Bellandur study area. It does not simulate hydraulic behaviour,
surface-to-drainage transfer, surcharge, overflow, SWMM, or PySWMM.

## Study area and CRS

The builder reads `config/study_area.json` and does not contain a second
coordinate definition. Public GeoJSON uses `EPSG:4326`; metric coordinates and
length calculations use the P3 working CRS, `EPSG:32643`. Drainage endpoints
are snapped within 5 m separately by source to avoid silently merging
independently mapped features.

## Sources investigated and used

### Government / observed

The primary drainage geometry is the combined 2022 Bengaluru Stormwater Drains
Map published through OpenCity for BBMP, with KSRSAC listed as the source:

<https://data.opencity.in/dataset/bengaluru-stormwater-drains-maps>

The raw KML is preserved at
`data/drainage/raw/bbmp_ksrsac_stormwater_drains_2022.kml`. Its primary,
secondary, and tertiary stormwater-drain classifications are retained in
`mapped_class`. The geometry is clipped to the Bellandur bbox; it is not treated
as a complete underground network or as a hydraulic survey.

### OSM / observed open mapping

The builder queries Overpass for mapped `waterway` classes relevant to drainage
(`drain`, `ditch`, `stream`, `canal`, `river`, `culvert`) plus mapped drain,
culvert, manhole, inlet, and catch-basin-like features. The raw response is
preserved at `data/drainage/raw/osm_drainage_overpass.json`. OSM waterway
classification is preserved and is not re-labelled as engineered municipal
drainage.

OSM attribution and licensing information: <https://www.openstreetmap.org/copyright>

### Terrain-inferred

P2 `flow_accumulation.tif` and the buffered DEM are used to select at most 15
high-accumulation cells inside the canonical bbox, with 90 m minimum spacing.
These become `source = "terrain_inferred"` inlet candidates only. They are not
claimed to be real manholes, inlets, or drains.

### Synthetic

No synthetic drainage links or synthetic municipal features were created in
this build. The one government-derived node marked `outfall_candidate` is a
candidate receiving point near the canonical study-area centre; its mapped
drain connectivity and hydraulic outfall status are explicitly unverified.

## Graph schema

The graph is directed as `from_node → to_node`. For mapped linework, the source
geometry order is retained as the explicit direction, with
`direction_status = "explicit_but_hydraulically_unverified"`. This is a graph
orientation for later review, not a claim about measured flow direction.

Node fields include:

`node_id`, `node_type`, `source`, `latitude`, `longitude`, `x_m`, `y_m`,
`ground_elevation_m`, `invert_elevation_m`, `capacity_m3s`, `status`,
`source_ids`, and `metadata`.

Link fields include:

`link_id`, `from_node`, `to_node`, `link_type`, `source`, `source_id`,
`mapped_class`, `geometry`, `length_m`, `direction`, `direction_status`,
`slope`, `diameter_m`, `width_m`, `capacity_m3s`, `invert_elevation_m`, and
`metadata`.

Unknown hydraulic values remain null. In particular, DEM ground elevation is
not copied into invert elevation, and no pipe diameter, capacity, flow rate, or
hydraulic slope is fabricated.

## Surface-to-drainage candidates

`surface_drainage_connections.geojson` associates each terrain-inferred flow-
accumulation candidate with its nearest observed drainage node. It stores the
surface cell identifier, distance, method, confidence flag, and a line
geometry for inspection. Every record is marked
`candidate_only_no_transfer_simulated`; it does not create a water-transfer
operation.

## Outputs

- `data/drainage/processed/drainage_nodes.geojson`
- `data/drainage/processed/drainage_links.geojson`
- `data/drainage/processed/drainage_network.graphml`
- `data/drainage/processed/surface_drainage_connections.geojson`
- `data/drainage/metadata/drainage_network.json`
- `data/drainage/validation/p4_validation.json`
- `data/drainage/validation/preview/p4_qa_context.geojson`

The QA context contains drainage nodes, drainage links, surface-association
candidates, and the existing OSM road context for GIS inspection. It is not a
frontend layer and does not alter the frontend.

## Current validation result

The current deterministic build contains 91 nodes, 45 links, and 15
surface-association candidates. It reports 46 weakly connected components and
15 orphan nodes; the orphan nodes are the terrain-inferred candidates because
association candidates are intentionally not drainage links. All graph and
schema checks pass, all 91 node ground elevations have valid DEM samples, and
all 91 invert elevations remain unresolved/null.

## Limitations and exact next phase

The KML and OSM layers do not provide a complete, surveyed underground network
for this prototype extent. Mapped geometry may be incomplete, stale, or
classified differently from engineered stormwater infrastructure. Line order
is not verified hydraulic direction. The network has no calibrated roughness,
invert survey, diameter inventory, capacity, or observed hydraulic state.

The exact next phase is **P5 — EPA SWMM / PySWMM Hydraulic Simulation**.
