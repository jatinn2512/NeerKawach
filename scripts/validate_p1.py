"""Run read-only P1 consistency checks for the canonical Bellandur foundation."""

from __future__ import annotations

import csv
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from p1_common import ROOT, load_study_area


def inside(lon: float, lat: float, bbox: dict) -> bool:
    return bbox["min_lon"] - 1e-9 <= lon <= bbox["max_lon"] + 1e-9 and bbox["min_lat"] - 1e-9 <= lat <= bbox["max_lat"] + 1e-9


def main() -> None:
    area = load_study_area()
    bbox = area["bbox"]
    checks: list[tuple[str, bool, str]] = []
    dem_meta_path = ROOT / "data/dem/metadata/srtm_n12e077.json"
    dem_raw_path = ROOT / "data/dem/raw/N12E077.hgt.gz"
    dem = json.loads(dem_meta_path.read_text(encoding="utf-8")) if dem_meta_path.exists() else {}
    tile = dem.get("tile_extent", {})
    checks.append(("study area bbox is ordered and EPSG:4326", True, str(area["bbox"])))
    checks.append(("DEM raw and metadata exist", dem_raw_path.exists() and dem_meta_path.exists(), str(dem_raw_path)))
    checks.append(("DEM tile covers study area", all((tile.get("min_lat", 0) <= bbox["min_lat"], tile.get("max_lat", 0) >= bbox["max_lat"], tile.get("min_lon", 0) <= bbox["min_lon"], tile.get("max_lon", 0) >= bbox["max_lon"])), str(tile)))
    roads_path = ROOT / "data/roads/processed/bellandur_roads.geojson"
    graph_path = ROOT / "data/roads/processed/bellandur_roads.graphml"
    raw_roads_path = ROOT / "data/roads/raw/bellandur_highways_overpass.json"
    roads = json.loads(roads_path.read_text(encoding="utf-8")) if roads_path.exists() else {"features": []}
    road_points = []
    for feature in roads.get("features", []):
        geometry = feature.get("geometry", {})
        lines = [geometry.get("coordinates", [])] if geometry.get("type") == "LineString" else geometry.get("coordinates", [])
        road_points.extend(point for line in lines for point in line)
    roads_in_area = bool(road_points) and all(inside(float(point[0]), float(point[1]), bbox) for point in road_points)
    checks.append(("road raw, GeoJSON and GraphML exist", raw_roads_path.exists() and roads_path.exists() and graph_path.exists(), str(roads_path)))
    checks.append(("processed road geometry stays inside study bbox", roads_in_area, f"{len(roads.get('features', []))} features"))
    try:
        ET.parse(graph_path)
        graph_ok = True
    except (FileNotFoundError, ET.ParseError):
        graph_ok = False
    checks.append(("GraphML is well-formed XML", graph_ok, str(graph_path)))
    rainfall_path = ROOT / "data/rainfall/processed/imd_gpm_2026-09-17.csv"
    rainfall_meta_path = ROOT / "data/rainfall/metadata/imd_gpm_2026-09-17.json"
    rainfall_meta = json.loads(rainfall_meta_path.read_text(encoding="utf-8")) if rainfall_meta_path.exists() else {}
    rainfall_rows = list(csv.DictReader(rainfall_path.open(encoding="utf-8"))) if rainfall_path.exists() else []
    footprint_covers = False
    for row in rainfall_rows:
        lat, lon = float(row["latitude"]), float(row["longitude"])
        half = float(rainfall_meta.get("grid_definition", {}).get("step", 0.25)) / 2
        footprint_covers = footprint_covers or not (lat + half < bbox["min_lat"] or lat - half > bbox["max_lat"] or lon + half < bbox["min_lon"] or lon - half > bbox["max_lon"])
        if float(row["rainfall_mm"]) < 0:
            footprint_covers = False
    checks.append(("rainfall raw, processed and metadata exist", (ROOT / "data/rainfall/raw/imd/17092026.grd").exists() and rainfall_path.exists() and rainfall_meta_path.exists(), str(rainfall_path)))
    checks.append(("rainfall source grid footprint covers study area", bool(rainfall_rows) and footprint_covers, f"{len(rainfall_rows)} valid intersecting grid-cell record(s)"))
    checks.append(("rainfall CRS and temporal resolution documented", rainfall_meta.get("crs") == "EPSG:4326" and bool(rainfall_meta.get("temporal_resolution")), rainfall_meta.get("temporal_resolution", "missing")))
    failures = 0
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {name} [{detail}]")
        failures += not passed
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
