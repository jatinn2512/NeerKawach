# P8 Flood-Safe Dynamic Routing

P8 is a downstream routing layer over the locked P1 road network and the
validated P7 road-impact products. It does not rerun rainfall, terrain,
surface-water, drainage, or hydraulic models.

## Inputs

- Directed GraphML: `data/roads/processed/bellandur_roads.graphml`
- Road GeoJSON source: `data/roads/processed/bellandur_roads.geojson`
- P7 timestamped road impacts: `data/inundation/roads/road_impact_timeseries.csv`
- P7 maximum road summary: `data/inundation/roads/road_impact_summary.csv`
- Canonical study area: `config/study_area.json`

GraphML directionality is preserved. Existing reverse edges are used when OSM
indicates bidirectional travel; one-way edges are not reversed by P8.

## Configured routing assumptions

`config/routing.json` defines project assumptions:

- `0.05 m`: flooded threshold, inherited from the P7 threshold;
- `0.30 m`: project-defined closure threshold;
- `10.0`: flooded-edge penalty factor;
- `500 m`: maximum point-to-node snapping distance.

These are prototype routing assumptions, not universal engineering standards,
legal closure rules, observed passability limits, or traffic guidance.

For a flooded but traversable edge, cost is:

`length_m * (1 + flood_penalty_factor * depth_m / closure_threshold_m)`

Edges at or above the closure threshold are excluded only from the
flood-aware search. The base graph is never permanently edited. Edges with no
timestamped P7 value are not treated as dry: they remain available to the
baseline comparison but are excluded from flood-aware routing.

## Routing behavior

The command accepts origin/destination longitude-latitude points and an exact
P7 timestamp:

```powershell
python scripts/data/route_flood_safe.py `
  --origin-lat 12.9251483 --origin-lon 77.6644403 `
  --destination-lat 12.9407548 --destination-lon 77.6572335 `
  --timestamp 2026-01-01T00:50:00Z `
  --output-stem bellandur_demo
```

It snaps both points to existing GraphML nodes and returns baseline and
flood-aware paths, route status, distances, costs, maximum route depth,
affected segments, and avoided flooded segments. A flood-aware no-route result
does not delete or alter the base graph.

Outputs are written under `data/routing/routes`, `data/routing/metrics`, and
`data/routing/metadata`. GeoJSON output is EPSG:4326 and includes baseline and
flood-aware LineString features where available.

## Limitations and provenance

P8 uses modeled P7 road-intersection depths, not observations. It has no live
traffic, travel-time, vehicle, road-elevation, legal-closure, or pavement
condition data. The route cost is a deterministic prototype cost. Source paths,
study area, timestamp, thresholds, join coverage, and generation time are
recorded in each provenance JSON file.
