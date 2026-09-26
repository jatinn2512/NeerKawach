# Neer Kawach P1 — Bellandur data foundation

Status: complete for the P1 acquisition/normalization scope. This document is the hand-off contract for P2 and later phases. The locked study city is Bengaluru, Karnataka; the locked primary study area is Bellandur.

## Study area

The single source of truth is [`config/study_area.json`](../config/study_area.json). Every P1 acquisition script reads this file.

| Field | Value |
|---|---|
| City | Bengaluru |
| State | Karnataka |
| Country | India |
| CRS | EPSG:4326 |
| Bbox | min_lat 12.925, min_lon 77.650, max_lat 12.945, max_lon 77.670 |
| Approximate area | 4.82 km² (spherical Earth area of the bbox) |
| Geographic rationale | Bellandur Lake anchor, lake-edge lowlands, Bellandur Road/ORR urban roads and surrounding flow-path context |

The coordinates were checked against the OpenStreetMap Bellandur map view and the Bellandur Lake map anchor. The extent is intentionally a bbox rather than a municipal boundary so that road, DEM and rainfall extraction remain reproducible. The DEM tile is larger than the study area by design; the processed road and rainfall artifacts are restricted or subset to the canonical extent.

References: [OpenStreetMap Bellandur map](https://www.openstreetmap.org/#map=14/12.9352/77.6649), [Bellandur map reference](https://maps.apple.com/place?auid=8458407851321227372).

## DEM

Selected source: NASA/USGS SRTMGL1.003, downloaded as the public AWS Terrain Tiles HGT tile `N12E077`.

- Raw file: [`data/dem/raw/N12E077.hgt.gz`](../data/dem/raw/N12E077.hgt.gz)
- Metadata: [`data/dem/metadata/srtm_n12e077.json`](../data/dem/metadata/srtm_n12e077.json)
- Source: [NASA/USGS SRTMGL1.003](https://data.nasa.gov/dataset/nasa-shuttle-radar-topography-mission-global-1-arc-second-v003-e47e1); [public tile URL](https://s3.amazonaws.com/elevation-tiles-prod/skadi/N12/N12E077.hgt.gz)
- Resolution: 1 arc-second, approximately 30 m nominal; approximately 27 m east-west at Bellandur
- CRS: EPSG:4326
- Tile extent: 12–13°N, 77–78°E; it fully covers the Bellandur bbox
- Nodata: -32768; no nodata cells were found in the downloaded tile
- Units: metres
- Tile valid elevation range: 233–1505 m; cells intersecting the Bellandur bbox range from 869–899 m
- Acquisition: 2026-09-18 UTC

Only download, checksum, HGT dimension inspection and an in-area elevation-range check were performed. No clipping, resampling, slope, aspect, flow direction, accumulation, sink/depression, runoff or flood-depth calculation was performed. P2 should first convert/clip the raw HGT to a working raster with a small buffer and record the vertical datum decision.

Candidate comparison: SRTM was selected over a credentialed Earthdata workflow because it is globally covering, public, simple to reproduce for this small area and adequate as a first 30 m urban DEM. Copernicus/ALOS products may be evaluated in a later accuracy pass, but are not necessary to establish P1.

## OSM road network

Source: OpenStreetMap contributors via the public Overpass API. The query is restricted to the canonical bbox and requests `way["highway"]`, preserving OSM tags where available. The raw response is retained; processed geometry is clipped to the bbox because some ways cross the query boundary.

- Raw response: [`data/roads/raw/bellandur_highways_overpass.json`](../data/roads/raw/bellandur_highways_overpass.json)
- GraphML: [`data/roads/processed/bellandur_roads.graphml`](../data/roads/processed/bellandur_roads.graphml)
- GeoJSON: [`data/roads/processed/bellandur_roads.geojson`](../data/roads/processed/bellandur_roads.geojson)
- Metadata: [`data/roads/processed/metadata.json`](../data/roads/processed/metadata.json)
- Extraction: 2026-09-18 UTC
- CRS: EPSG:4326
- Result: 248 highway ways; processed bounds exactly match the study bbox
- Attributes retained: OSM way/node identifiers, highway, name, oneway, maxspeed, surface, lanes, bridge, tunnel and segment geometry
- License: OpenStreetMap data is ODbL; retain attribution to OpenStreetMap contributors

The GraphML is a directed edge representation for later NetworkX/OSMnx use. No Dijkstra, A*, route blocking, safe-route logic or API integration is present in P1.

References: [OSM copyright and license](https://www.openstreetmap.org/copyright), [Overpass API](https://overpass-api.de/api/status), [OSMnx bbox reference](https://osmnx.readthedocs.io/en/stable/user-reference.html).

## Rainfall sources investigated

The source-by-source record is [`data/rainfall/metadata/source_catalog.json`](../data/rainfall/metadata/source_catalog.json).

| Candidate | Resolution | P1 status | Decision |
|---|---:|---|---|
| IMD DWR/radar-derived QPE | Product/request dependent | Official Radar Data Supply Portal requires registration/request; no anonymous historical Bellandur QPE download was verified | Keep as a future plug-in; do not fabricate or call the selected file radar |
| IMD AWS/ARG | Point station; temporal sampling varies | Official API documentation is public, but the AWS mapping endpoint returned HTTP 401 in this run; no Bellandur station series acquired | Keep as a future point-observation source |
| IMD gauge-only gridded rainfall | 0.25° daily | Official archive/download page exists | Candidate for historical daily baseline |
| IMD/NCMRWF GPM-merged rainfall | 0.25° daily | Public binary download succeeded for 2026-09-17 | Selected P1 usable source |
| NASA GPM IMERG | 0.1° (~10 km), 30 min | Official metadata is public; direct PPS/GES DISC download path was not anonymously accessible in this run | Keep as source-agnostic supplement/fallback |

The selected file is **IMD/NCMRWF daily merged satellite-gauge rainfall (GPM-based)**. It is not radar, not street-level, and not a historical DWR substitute. The acquired record is a current daily foundation sample for 2026-09-17, with one valid source cell whose footprint intersects the Bellandur bbox.

Selected rainfall files:

- Raw binary: [`data/rainfall/raw/imd/17092026.grd`](../data/rainfall/raw/imd/17092026.grd)
- Provider control file: [`data/rainfall/raw/imd/imd_gpm_template.ctl`](../data/rainfall/raw/imd/imd_gpm_template.ctl)
- Normalized data: [`data/rainfall/processed/imd_gpm_2026-09-17.csv`](../data/rainfall/processed/imd_gpm_2026-09-17.csv)
- Metadata: [`data/rainfall/metadata/imd_gpm_2026-09-17.json`](../data/rainfall/metadata/imd_gpm_2026-09-17.json)

The normalized schema is:

```text
timestamp, latitude, longitude, rainfall_mm, source
```

For gridded data, latitude/longitude are the source cell center and the metadata records the 0.25° footprint. A cell center can therefore be just outside the study bbox while its footprint covers the bbox; no finer resolution is implied. For station sources, preserve station identifiers and station metadata in the sidecar rather than converting a point into a grid.

## Reproducible scripts

- [`scripts/acquire_dem.py`](../scripts/acquire_dem.py): download and inspect the raw SRTM HGT tile only.
- [`scripts/acquire_osm_roads.py`](../scripts/acquire_osm_roads.py): query Overpass, preserve raw JSON, clip processed road geometry and emit GraphML/GeoJSON.
- [`scripts/acquire_imd_rainfall.py`](../scripts/acquire_imd_rainfall.py): download one IMD GPM-merged daily binary and subset intersecting source cells.
- [`scripts/normalize_rainfall.py`](../scripts/normalize_rainfall.py): validate/normalize CSV station or grid records to the generic rainfall schema.
- [`scripts/validate_p1.py`](../scripts/validate_p1.py): run read-only P1 data-quality and spatial consistency checks.

Run from the repository root with the project Python interpreter:

```powershell
python scripts/acquire_dem.py
python scripts/acquire_osm_roads.py
python scripts/acquire_imd_rainfall.py --date 17092026
python scripts/validate_p1.py
```

To add DWR, ARG/AWS, IMD-grid or IMERG later, place the untouched provider file under its matching `data/rainfall/raw/<source>/` directory, write a source metadata sidecar, then map the provider fields into the canonical CSV using `normalize_rainfall.py`. Keep the native spatial and temporal resolution in metadata; do not resample merely to make sources look identical.

## P1 checks and limitations

The final check confirms: one canonical bbox; DEM coverage; road coverage and processed geometry bounds; rainfall cell-footprint coverage; CRS documentation; DEM/rainfall/road resolution metadata; rainfall temporal resolution; raw/processed separation; and traceable source URLs. The road raw/processed extent was specifically checked after clipping.

Limitations remaining by design: SRTM is a 30 m surface/elevation product, not a drainage survey; the selected rainfall is daily and 0.25°; IMD AWS/ARG station history was not accessible anonymously; DWR historical QPE was not publicly downloadable without an access request; and no urban flood modelling or routing has been implemented.

## P2 starting point

Start P2 by converting the preserved [`N12E077.hgt.gz`](../data/dem/raw/N12E077.hgt.gz) into a buffered, study-area working raster, documenting the vertical reference and clip window, and only then deriving terrain products. Do not use the rainfall or road artifacts as inputs to terrain processing, and do not implement runoff, flow accumulation, flood depth or routing in this hand-off.
