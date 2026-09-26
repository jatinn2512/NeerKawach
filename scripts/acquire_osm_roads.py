"""Acquire Bellandur roads from Overpass and export OSM-compatible artifacts.

Uses the Overpass JSON API directly to keep P1 reproducible with Python's standard
library. The resulting GraphML is suitable for NetworkX/OSMnx and the GeoJSON is
for GIS inspection. No routing is performed.
"""

from __future__ import annotations

import argparse
import html
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from p1_common import ROOT, bbox_tuple, load_study_area


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
RAW_PATH = ROOT / "data" / "roads" / "raw" / "bellandur_highways_overpass.json"
GRAPH_PATH = ROOT / "data" / "roads" / "processed" / "bellandur_roads.graphml"
GEOJSON_PATH = ROOT / "data" / "roads" / "processed" / "bellandur_roads.geojson"
METADATA_PATH = ROOT / "data" / "roads" / "processed" / "metadata.json"


def query(bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    return f'[out:json][timeout:120];way["highway"]({south},{west},{north},{east});out body geom;'


def get_json(query_text: str) -> dict:
    payload = urllib.parse.urlencode({"data": query_text}).encode("utf-8")
    request = urllib.request.Request(
        OVERPASS_URL,
        data=payload,
        headers={"User-Agent": "Neer Kawach-P1/1.0 (SIH prototype)"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def tag(tags: dict, key: str, default: str = "") -> str:
    value = tags.get(key, default)
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    return str(value)


def clip_segment(a: dict, b: dict, bbox: tuple[float, float, float, float]) -> tuple[dict, dict] | None:
    """Clip one lon/lat segment to south, west, north, east."""
    south, west, north, east = bbox
    x0, y0, x1, y1 = a["lon"], a["lat"], b["lon"], b["lat"]
    dx, dy = x1 - x0, y1 - y0
    p = (-dx, dx, -dy, dy)
    q = (x0 - west, east - x0, y0 - south, north - y0)
    u0, u1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None
            continue
        ratio = qi / pi
        if pi < 0:
            if ratio > u1:
                return None
            u0 = max(u0, ratio)
        else:
            if ratio < u0:
                return None
            u1 = min(u1, ratio)
    start = {"lon": x0 + u0 * dx, "lat": y0 + u0 * dy}
    end = {"lon": x0 + u1 * dx, "lat": y0 + u1 * dy}
    return start, end


def clipped_segments(element: dict, bbox: tuple[float, float, float, float]) -> list[tuple[int | str, int | str, dict, dict]]:
    geometry = element.get("geometry", [])
    refs = element.get("nodes", [])
    if len(geometry) < 2 or len(refs) != len(geometry):
        return []
    result = []
    for index, (left, right) in enumerate(zip(geometry, geometry[1:])):
        clipped = clip_segment(left, right, bbox)
        if clipped is None:
            continue
        start, end = clipped
        bbox_values = (bbox[0], bbox[1], bbox[2], bbox[3])
        start_inside = bbox_values[0] <= left["lat"] <= bbox_values[2] and bbox_values[1] <= left["lon"] <= bbox_values[3]
        end_inside = bbox_values[0] <= right["lat"] <= bbox_values[2] and bbox_values[1] <= right["lon"] <= bbox_values[3]
        start_id = refs[index] if start_inside else f"clip:{start['lon']:.7f}:{start['lat']:.7f}"
        end_id = refs[index + 1] if end_inside else f"clip:{end['lon']:.7f}:{end['lat']:.7f}"
        result.append((start_id, end_id, start, end))
    return result


def build_geojson(elements: list[dict], bbox: tuple[float, float, float, float]) -> dict:
    features = []
    for element in elements:
        pieces = clipped_segments(element, bbox)
        if not pieces:
            continue
        tags = element.get("tags", {})
        lines = [[[piece[2]["lon"], piece[2]["lat"]], [piece[3]["lon"], piece[3]["lat"]]] for piece in pieces]
        geometry = {"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else {"type": "MultiLineString", "coordinates": lines}
        features.append({
            "type": "Feature",
            "id": f"way/{element['id']}",
            "properties": {
                "osm_id": element["id"],
                "highway": tag(tags, "highway"),
                "name": tag(tags, "name"),
                "oneway": tag(tags, "oneway"),
                "maxspeed": tag(tags, "maxspeed"),
                "surface": tag(tags, "surface"),
                "lanes": tag(tags, "lanes"),
                "bridge": tag(tags, "bridge"),
                "tunnel": tag(tags, "tunnel"),
            },
            "geometry": geometry,
        })
    return {"type": "FeatureCollection", "name": "bellandur_roads", "features": features}


def graphml(elements: list[dict], bbox: tuple[float, float, float, float]) -> str:
    nodes: dict[str, tuple[float, float]] = {}
    edges: list[dict] = []
    for way in elements:
        pieces = clipped_segments(way, bbox)
        if not pieces:
            continue
        tags = way.get("tags", {})
        oneway = tag(tags, "oneway").lower()
        for index, (source, target, start, end) in enumerate(pieces):
            nodes.setdefault(str(source), (start["lon"], start["lat"]))
            nodes.setdefault(str(target), (end["lon"], end["lat"]))
            attrs = {
                "osm_way_id": way["id"], "segment": index,
                "highway": tag(tags, "highway"), "name": tag(tags, "name"),
                "oneway": tag(tags, "oneway"), "maxspeed": tag(tags, "maxspeed"),
                "surface": tag(tags, "surface"), "lanes": tag(tags, "lanes"),
                "geometry": f"LINESTRING ({start['lon']} {start['lat']}, {end['lon']} {end['lat']})",
            }
            if oneway == "-1":
                source, target = target, source
            edges.append({"source": str(source), "target": str(target), "key": f"{way['id']}_{index}", "attrs": attrs})
            if oneway not in {"yes", "true", "1", "-1"}:
                edges.append({"source": str(target), "target": str(source), "key": f"{way['id']}_{index}_reverse", "attrs": attrs})
    esc = lambda value: html.escape(str(value), quote=True)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">',
        '<key id="x" for="node" attr.name="x" attr.type="double"/><key id="y" for="node" attr.name="y" attr.type="double"/>',
    ]
    keys = {"osm_way_id": "long", "segment": "int", "highway": "string", "name": "string", "oneway": "string", "maxspeed": "string", "surface": "string", "lanes": "string", "geometry": "string"}
    for key, dtype in keys.items():
        lines.append(f'<key id="{key}" for="edge" attr.name="{key}" attr.type="{dtype}"/>')
    lines.append('<graph id="bellandur_roads" edgedefault="directed">')
    for node_id, (lon, lat) in nodes.items():
        lines.append(f'<node id="{esc(node_id)}"><data key="x">{lon}</data><data key="y">{lat}</data></node>')
    for edge in edges:
        lines.append(f'<edge id="{esc(edge["key"])}" source="{esc(edge["source"])}" target="{esc(edge["target"])}">')
        for key, value in edge["attrs"].items():
            lines.append(f'<data key="{key}">{esc(value)}</data>')
        lines.append('</edge>')
    lines.extend(['</graph>', '</graphml>'])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    area = load_study_area()
    bbox = bbox_tuple(area)
    for path in (RAW_PATH, GRAPH_PATH, GEOJSON_PATH, METADATA_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
    if args.force or not RAW_PATH.exists():
        data = get_json(query(bbox))
        RAW_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    data = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    elements = [element for element in data.get("elements", []) if element.get("type") == "way"]
    geojson = build_geojson(elements, bbox)
    GEOJSON_PATH.write_text(json.dumps(geojson, indent=2) + "\n", encoding="utf-8")
    GRAPH_PATH.write_text(graphml(elements, bbox), encoding="utf-8")
    metadata = {
        "source": "OpenStreetMap contributors via Overpass API",
        "source_url": "https://www.openstreetmap.org/copyright",
        "overpass_url": OVERPASS_URL,
        "extraction_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "method": "Overpass QL way[highway] bbox query; raw JSON preserved; GeoJSON and directed GraphML exports generated without routing",
        "bbox": area["bbox"], "crs": "EPSG:4326",
        "way_count": len(geojson["features"]),
        "raw_file": str(RAW_PATH.relative_to(ROOT)).replace("\\", "/"),
        "graphml_file": str(GRAPH_PATH.relative_to(ROOT)).replace("\\", "/"),
        "geojson_file": str(GEOJSON_PATH.relative_to(ROOT)).replace("\\", "/"),
        "license": "Open Database License (ODbL); attribution to OpenStreetMap contributors required",
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
