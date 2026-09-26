"""Build the P4 Bellandur drainage-network foundation.

This script creates a directed, provenance-aware network foundation only. It
does not simulate hydraulics, transfer surface water, calculate capacity, or
run SWMM/PySWMM. Government KML and OSM geometry are preserved separately from
terrain-inferred candidates, and unknown hydraulic attributes remain null.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform as project_points


ROOT = Path(__file__).resolve().parents[2]
AREA_PATH = ROOT / "config" / "study_area.json"
RAW_DIR = ROOT / "data" / "drainage" / "raw"
PROCESSED_DIR = ROOT / "data" / "drainage" / "processed"
METADATA_DIR = ROOT / "data" / "drainage" / "metadata"
VALIDATION_DIR = ROOT / "data" / "drainage" / "validation"
PREVIEW_DIR = VALIDATION_DIR / "preview"

GOVERNMENT_KML = RAW_DIR / "bbmp_ksrsac_stormwater_drains_2022.kml"
OSM_RAW = RAW_DIR / "osm_drainage_overpass.json"
NODES_GEOJSON = PROCESSED_DIR / "drainage_nodes.geojson"
LINKS_GEOJSON = PROCESSED_DIR / "drainage_links.geojson"
GRAPHML_PATH = PROCESSED_DIR / "drainage_network.graphml"
CONNECTIONS_GEOJSON = PROCESSED_DIR / "surface_drainage_connections.geojson"
PREVIEW_GEOJSON = PREVIEW_DIR / "p4_qa_context.geojson"
METADATA_PATH = METADATA_DIR / "drainage_network.json"
VALIDATION_PATH = VALIDATION_DIR / "p4_validation.json"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
WORKING_CRS = "EPSG:32643"
PUBLIC_CRS = "EPSG:4326"
SNAP_TOLERANCE_M = 5.0
CONNECTION_MAX_DISTANCE_M = 600.0
SCRIPT_VERSION = "p4-drainage-network-1.0.0"

KML_NS = "{http://www.opengis.net/kml/2.2}"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bbox(area: dict) -> tuple[float, float, float, float]:
    b = area["bbox"]
    return float(b["min_lat"]), float(b["min_lon"]), float(b["max_lat"]), float(b["max_lon"])


def parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def tag(tags: dict, key: str, default: str = "") -> str:
    value = tags.get(key, default)
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    return str(value)


def overpass_query(area_bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = area_bbox
    return (
        f"[out:json][timeout:120];("
        f"way[waterway~\"drain|ditch|stream|canal|river|culvert\",i]({south},{west},{north},{east});"
        f"way[man_made=drain]({south},{west},{north},{east});"
        f"way[man_made=culvert]({south},{west},{north},{east});"
        f"node[man_made~\"manhole|inlet|catch_basin|storm_drain\",i]({south},{west},{north},{east});"
        f"node[waterway]({south},{west},{north},{east});"
        f");out body geom;"
    )


def download_overpass(area_bbox: tuple[float, float, float, float]) -> dict:
    payload = urllib.parse.urlencode({"data": overpass_query(area_bbox)}).encode("utf-8")
    failures = []
    for endpoint in OVERPASS_URLS:
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"User-Agent": "Neer Kawach-P4/1.0 (SIH prototype; drainage foundation)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)
        except Exception as error:  # pragma: no cover - endpoint availability varies
            failures.append(f"{endpoint}: {error}")
    raise RuntimeError("All Overpass endpoints failed: " + "; ".join(failures))


def clip_segment(a: tuple[float, float], b: tuple[float, float], area_bbox: tuple[float, float, float, float]) -> tuple[tuple[float, float], tuple[float, float]] | None:
    south, west, north, east = area_bbox
    x0, y0 = a
    x1, y1 = b
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
    return ((x0 + u0 * dx, y0 + u0 * dy), (x0 + u1 * dx, y0 + u1 * dy))


def clip_polyline(coords: list[tuple[float, float]], area_bbox: tuple[float, float, float, float]) -> list[list[tuple[float, float]]]:
    """Clip a line without changing its geometry order."""
    pieces: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for left, right in zip(coords, coords[1:]):
        clipped = clip_segment(left, right, area_bbox)
        if clipped is None:
            if len(current) >= 2:
                pieces.append(current)
            current = []
            continue
        start, end = clipped
        if not current:
            current = [start, end]
        elif math.dist(current[-1], start) <= 1e-10:
            if math.dist(current[-1], end) > 1e-10:
                current.append(end)
        else:
            if len(current) >= 2:
                pieces.append(current)
            current = [start, end]
    if len(current) >= 2:
        pieces.append(current)
    return pieces


def parse_kml() -> list[dict]:
    root = ET.parse(GOVERNMENT_KML).getroot()
    features: list[dict] = []
    for index, placemark in enumerate(root.iter(KML_NS + "Placemark"), start=1):
        name_node = placemark.find(KML_NS + "name")
        fields = {item.attrib.get("name", ""): (item.text or "").strip() for item in placemark.iter(KML_NS + "SimpleData")}
        source_id = fields.get("OBJECTID") or fields.get("OBJECTID_1") or str(index)
        display_name = (name_node.text or "").strip() if name_node is not None else ""
        geometries = []
        for coordinate_node in placemark.iter(KML_NS + "coordinates"):
            coords: list[tuple[float, float]] = []
            for token in (coordinate_node.text or "").replace("\n", " ").split():
                values = token.split(",")
                if len(values) >= 2:
                    lon, lat = parse_float(values[0]), parse_float(values[1])
                    if lon is not None and lat is not None:
                        coords.append((lon, lat))
            if len(coords) >= 2:
                geometries.append(coords)
        for part_index, coords in enumerate(geometries):
            features.append({
                "source": "government_dataset",
                "source_name": "BBMP/KSRSAC Bengaluru Stormwater Drains Map 2022",
                "source_id": f"gov:{source_id}:{part_index}",
                "name": display_name,
                "mapped_class": fields.get("Type") or fields.get("Layer") or "unknown",
                "fields": fields,
                "coordinates": coords,
            })
    return features


def parse_osm(payload: dict) -> tuple[list[dict], list[dict]]:
    lines: list[dict] = []
    points: list[dict] = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        if element.get("type") == "way" and len(element.get("geometry", [])) >= 2:
            lines.append({
                "source": "observed_osm",
                "source_name": "OpenStreetMap contributors via Overpass API",
                "source_id": f"osm:way:{element.get('id')}",
                "name": tag(tags, "name"),
                "mapped_class": tag(tags, "waterway") or tag(tags, "man_made") or "unknown",
                "fields": tags,
                "coordinates": [(float(point["lon"]), float(point["lat"])) for point in element["geometry"]],
            })
        elif element.get("type") == "node" and tags:
            node_type = "manhole" if tag(tags, "man_made").lower() == "manhole" else "inlet" if tag(tags, "man_made").lower() in {"inlet", "catch_basin", "storm_drain"} else "junction"
            if "lat" in element and "lon" in element:
                points.append({
                    "source": "observed_osm",
                    "source_name": "OpenStreetMap contributors via Overpass API",
                    "source_id": f"osm:node:{element.get('id')}",
                    "node_type": node_type,
                    "lon": float(element["lon"]),
                    "lat": float(element["lat"]),
                    "fields": tags,
                })
    return lines, points


def project(lons: list[float], lats: list[float]) -> tuple[list[float], list[float]]:
    xs, ys = project_points(PUBLIC_CRS, WORKING_CRS, lons, lats)
    return list(xs), list(ys)


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    xs, ys = project([a[0], b[0]], [a[1], b[1]])
    return math.hypot(xs[1] - xs[0], ys[1] - ys[0])


def line_length_m(coords: list[tuple[float, float]]) -> float:
    if len(coords) < 2:
        return 0.0
    xs, ys = project([point[0] for point in coords], [point[1] for point in coords])
    return float(sum(math.hypot(x1 - x0, y1 - y0) for x0, y0, x1, y1 in zip(xs, ys, xs[1:], ys[1:])))


def point_in_bbox(lon: float, lat: float, area_bbox: tuple[float, float, float, float]) -> bool:
    south, west, north, east = area_bbox
    return west <= lon <= east and south <= lat <= north


def choose_link_type(mapped_class: str) -> str:
    value = mapped_class.lower()
    if value in {"culvert", "box_culvert"}:
        return "culvert"
    if value in {"ditch", "drain"}:
        return value
    if value in {"stream", "river", "canal"}:
        return "open_channel"
    if value in {"primary", "secondary", "tertiary"}:
        return "drain"
    return "drain"


def sample_elevation(dataset: rasterio.DatasetReader, lon: float, lat: float) -> float | None:
    value = float(next(dataset.sample([(lon, lat)]))[0])
    if dataset.nodata is not None and math.isclose(value, float(dataset.nodata), abs_tol=0.0):
        return None
    return value if math.isfinite(value) else None


def make_feature(feature_id: str, properties: dict, geometry: dict) -> dict:
    return {"type": "Feature", "id": feature_id, "properties": properties, "geometry": geometry}


def wkt_line(coords: list[tuple[float, float]]) -> str:
    return "LINESTRING (" + ", ".join(f"{lon:.9f} {lat:.9f}" for lon, lat in coords) + ")"


def build_network(area: dict, osm_payload: dict) -> tuple[list[dict], list[dict], list[dict], dict]:
    area_bbox = bbox(area)
    government_features = parse_kml()
    osm_lines, osm_points = parse_osm(osm_payload)
    source_lines = [("government_dataset", item) for item in government_features] + [("observed_osm", item) for item in osm_lines]

    nodes_by_key: dict[tuple[str, int, int], dict] = {}
    node_uses: dict[str, list[str]] = defaultdict(list)
    links: list[dict] = []

    def node_for(source: str, lon: float, lat: float, node_type: str = "junction", source_id: str = "") -> str:
        x, y = project([lon], [lat])
        key = (source, round(x[0] / SNAP_TOLERANCE_M), round(y[0] / SNAP_TOLERANCE_M))
        if key not in nodes_by_key:
            nodes_by_key[key] = {"node_id": "", "node_type": node_type, "source": source, "lon": lon, "lat": lat, "source_ids": [], "status": "observed"}
        node = nodes_by_key[key]
        node["source_ids"].append(source_id)
        if node_type == "manhole" or node_type == "inlet":
            node["node_type"] = node_type
        node_uses[f"{source}:{key[1]}:{key[2]}"].append(source_id)
        return f"__node__:{source}:{key[1]}:{key[2]}"

    line_records: list[tuple[dict, str, str, list[tuple[float, float]]]] = []
    for source, item in sorted(source_lines, key=lambda pair: pair[1]["source_id"]):
        for part_index, clipped in enumerate(clip_polyline(item["coordinates"], area_bbox)):
            if len(clipped) < 2:
                continue
            from_ref = node_for(source, *clipped[0], source_id=item["source_id"])
            to_ref = node_for(source, *clipped[-1], source_id=item["source_id"])
            line_records.append((item, from_ref, to_ref, clipped))

    for item in sorted(osm_points, key=lambda point: point["source_id"]):
        if point_in_bbox(item["lon"], item["lat"], area_bbox):
            node_for("observed_osm", item["lon"], item["lat"], item["node_type"], item["source_id"])

    sorted_nodes = sorted(nodes_by_key.items(), key=lambda pair: pair[0])
    node_id_map: dict[str, str] = {}
    nodes: list[dict] = []
    for index, (key, node) in enumerate(sorted_nodes, start=1):
        reference = f"__node__:{key[0]}:{key[1]}:{key[2]}"
        node_id = f"drn_n_{index:05d}"
        node_id_map[reference] = node_id
        node["node_id"] = node_id
        nodes.append(node)

    for item in sorted(osm_points, key=lambda point: point["source_id"]):
        if not point_in_bbox(item["lon"], item["lat"], area_bbox):
            continue
        reference = node_for("observed_osm", item["lon"], item["lat"], item["node_type"], item["source_id"])
        node = next(node for node in nodes if node["node_id"] == node_id_map[reference])
        node["status"] = "observed"
        node["source_ids"].append(item["source_id"])

    for index, (item, from_ref, to_ref, coords) in enumerate(line_records, start=1):
        from_id, to_id = node_id_map[from_ref], node_id_map[to_ref]
        link_id = f"drn_l_{index:05d}"
        raw_fields = item.get("fields", {})
        links.append({
            "link_id": link_id,
            "from_node": from_id,
            "to_node": to_id,
            "link_type": choose_link_type(item["mapped_class"]),
            "source": item["source"],
            "source_id": item["source_id"],
            "mapped_class": item["mapped_class"],
            "name": item.get("name", ""),
            "direction": "forward_geometry_order",
            "direction_status": "explicit_but_hydraulically_unverified",
            "length_m": line_length_m(coords),
            "slope": None,
            "diameter_m": parse_float(raw_fields.get("diameter")),
            "width_m": parse_float(raw_fields.get("width")),
            "capacity_m3s": None,
            "invert_elevation_m": None,
            "geometry": coords,
            "metadata": {"raw_tags": raw_fields, "source_name": item["source_name"]},
        })

    # The endpoint closest to the canonical bbox centre is retained as an
    # explicit outfall candidate only; it is not asserted to be a surveyed
    # hydraulic outfall. The centre comes from the canonical study-area config.
    centre = ((area["bbox"]["min_lon"] + area["bbox"]["max_lon"]) / 2.0, (area["bbox"]["min_lat"] + area["bbox"]["max_lat"]) / 2.0)
    government_nodes = [node for node in nodes if node["source"] == "government_dataset"]
    if government_nodes:
        candidate = min(government_nodes, key=lambda node: distance_m((node["lon"], node["lat"]), centre))
        if distance_m((candidate["lon"], candidate["lat"]), centre) <= 800.0:
            candidate["node_type"] = "outfall"
            candidate["status"] = "outfall_candidate"
            candidate["metadata"] = {"basis": "mapped government drain endpoint nearest canonical study-area centre; receiving-water and hydraulic connectivity unverified"}

    # Sample DEM ground elevations after the graph topology is fixed.
    dem_path = ROOT / "data" / "dem" / "processed" / "bellandur_dem_buffered.tif"
    with rasterio.open(dem_path) as dem:
        for node in nodes:
            node["ground_elevation_m"] = sample_elevation(dem, node["lon"], node["lat"])
            node["invert_elevation_m"] = None
            node["capacity_m3s"] = None
            node["x_m"], node["y_m"] = project([node["lon"]], [node["lat"]])
            node["source_ids"] = sorted(set(node["source_ids"]))
            node["metadata"] = node.get("metadata", {})

    terrain_candidates = terrain_candidate_nodes(area, nodes)
    nodes.extend(terrain_candidates)
    connections = build_connections(terrain_candidates, [node for node in nodes if node["source"] in {"government_dataset", "observed_osm"}])
    return nodes, links, connections, {"government_feature_count": len(government_features), "osm_line_count": len(osm_lines), "osm_point_count": len(osm_points), "terrain_candidate_count": len(terrain_candidates)}


def terrain_candidate_nodes(area: dict, existing_nodes: list[dict]) -> list[dict]:
    accumulation_path = ROOT / "data" / "dem" / "terrain" / "flow_accumulation.tif"
    candidates: list[dict] = []
    with rasterio.open(accumulation_path) as accumulation, rasterio.open(ROOT / "data" / "dem" / "processed" / "bellandur_dem_buffered.tif") as dem:
        values = accumulation.read(1).astype(float)
        valid = np.isfinite(values) & (values != accumulation.nodata)
        south, west, north, east = bbox(area)
        rows, cols = np.where(valid)
        ranked = sorted(zip(values[rows, cols], rows, cols), reverse=True)
        selected: list[tuple[float, float]] = []
        for value, row, col in ranked:
            lon, lat = accumulation.transform @ (int(col) + 0.5, int(row) + 0.5)
            if not (west <= lon <= east and south <= lat <= north) or value < 10:
                continue
            if any(distance_m((lon, lat), point) < 90.0 for point in selected):
                continue
            selected.append((lon, lat))
            candidates.append({
                "node_id": f"terrain_candidate_{len(candidates) + 1:03d}",
                "node_type": "inlet",
                "source": "terrain_inferred",
                "lon": float(lon),
                "lat": float(lat),
                "x_m": project([float(lon)], [float(lat)])[0][0],
                "y_m": project([float(lon)], [float(lat)])[1][0],
                "ground_elevation_m": sample_elevation(dem, float(lon), float(lat)),
                "invert_elevation_m": None,
                "capacity_m3s": None,
                "source_ids": [f"flow_accumulation:r{int(row)}c{int(col)}"],
                "status": "candidate",
                "metadata": {"method": "top_flow_accumulation_cells_with_90m_spacing", "flow_accumulation_cells": float(value), "surface_cell_id": f"flow_accumulation:r{int(row)}c{int(col)}"},
            })
            if len(candidates) >= 15:
                break
    return candidates


def build_connections(candidates: list[dict], observed_nodes: list[dict]) -> list[dict]:
    connections = []
    for index, candidate in enumerate(candidates, start=1):
        if not observed_nodes:
            continue
        target = min(observed_nodes, key=lambda node: distance_m((candidate["lon"], candidate["lat"]), (node["lon"], node["lat"])))
        distance = distance_m((candidate["lon"], candidate["lat"]), (target["lon"], target["lat"]))
        quality = "high" if distance <= 60 else "medium" if distance <= 150 else "low" if distance <= CONNECTION_MAX_DISTANCE_M else "unresolved"
        connections.append({
            "connection_id": f"sfc_{index:03d}",
            "surface_cell_id": candidate["metadata"]["surface_cell_id"],
            "surface_latitude": candidate["lat"],
            "surface_longitude": candidate["lon"],
            "drainage_node_id": target["node_id"],
            "distance_m": distance,
            "source": "terrain_inferred",
            "confidence": quality,
            "method": "nearest_observed_drainage_node",
            "status": "candidate_only_no_transfer_simulated",
            "geometry": [(candidate["lon"], candidate["lat"]), (target["lon"], target["lat"])],
        })
    return connections


def write_geojson(path: Path, name: str, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"type": "FeatureCollection", "name": name, "crs": {"type": "name", "properties": {"name": PUBLIC_CRS}}, "features": features}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def node_features(nodes: list[dict]) -> list[dict]:
    result = []
    for node in nodes:
        properties = {key: value for key, value in node.items() if key not in {"node_id", "lon", "lat", "x_m", "y_m"}}
        properties.update({"node_id": node["node_id"], "x_m": node["x_m"], "y_m": node["y_m"], "ground_elevation_m": node.get("ground_elevation_m"), "invert_elevation_m": node.get("invert_elevation_m")})
        result.append(make_feature(node["node_id"], properties, {"type": "Point", "coordinates": [node["lon"], node["lat"]]}))
    return result


def link_features(links: list[dict]) -> list[dict]:
    result = []
    for link in links:
        properties = {key: value for key, value in link.items() if key not in {"link_id", "geometry"}}
        properties["link_id"] = link["link_id"]
        properties["geometry_crs"] = PUBLIC_CRS
        result.append(make_feature(link["link_id"], properties, {"type": "LineString", "coordinates": link["geometry"]}))
    return result


def connection_features(connections: list[dict]) -> list[dict]:
    result = []
    for connection in connections:
        properties = {key: value for key, value in connection.items() if key not in {"connection_id", "geometry"}}
        result.append(make_feature(connection["connection_id"], properties, {"type": "LineString", "coordinates": connection["geometry"]}))
    return result


def write_graphml(nodes: list[dict], links: list[dict]) -> None:
    namespace = "http://graphml.graphdrawing.org/xmlns"
    ET.register_namespace("", namespace)
    root = ET.Element(f"{{{namespace}}}graphml")
    node_keys = {"node_type": "string", "source": "string", "latitude": "double", "longitude": "double", "x_m": "double", "y_m": "double", "ground_elevation_m": "double", "invert_elevation_m": "double", "status": "string", "provenance": "string"}
    edge_keys = {"link_id": "string", "link_type": "string", "source": "string", "source_id": "string", "direction": "string", "direction_status": "string", "length_m": "double", "slope": "double", "diameter_m": "double", "width_m": "double", "capacity_m3s": "double", "geometry_wkt": "string"}
    for key, dtype in node_keys.items():
        ET.SubElement(root, f"{{{namespace}}}key", id=f"n_{key}", **{"for": "node", "attr.name": key, "attr.type": dtype})
    for key, dtype in edge_keys.items():
        ET.SubElement(root, f"{{{namespace}}}key", id=f"e_{key}", **{"for": "edge", "attr.name": key, "attr.type": dtype})
    graph = ET.SubElement(root, f"{{{namespace}}}graph", id="bellandur_drainage", edgedefault="directed")
    for node in nodes:
        element = ET.SubElement(graph, f"{{{namespace}}}node", id=node["node_id"])
        values = {"node_type": node["node_type"], "source": node["source"], "latitude": node["lat"], "longitude": node["lon"], "x_m": node["x_m"], "y_m": node["y_m"], "ground_elevation_m": node.get("ground_elevation_m"), "invert_elevation_m": node.get("invert_elevation_m"), "status": node.get("status", ""), "provenance": json.dumps(node.get("metadata", {}), sort_keys=True)}
        for key, value in values.items():
            if value is not None:
                ET.SubElement(element, f"{{{namespace}}}data", key=f"n_{key}").text = str(value)
    for link in links:
        element = ET.SubElement(graph, f"{{{namespace}}}edge", id=link["link_id"], source=link["from_node"], target=link["to_node"])
        values = {"link_id": link["link_id"], "link_type": link["link_type"], "source": link["source"], "source_id": link["source_id"], "direction": link["direction"], "direction_status": link["direction_status"], "length_m": link["length_m"], "slope": link.get("slope"), "diameter_m": link.get("diameter_m"), "width_m": link.get("width_m"), "capacity_m3s": link.get("capacity_m3s"), "geometry_wkt": wkt_line(link["geometry"])}
        for key, value in values.items():
            if value is not None:
                ET.SubElement(element, f"{{{namespace}}}data", key=f"e_{key}").text = str(value)
    GRAPHML_PATH.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(GRAPHML_PATH, encoding="utf-8", xml_declaration=True)


def build_preview(nodes: list[dict], links: list[dict], connections: list[dict]) -> None:
    features = []
    for feature in node_features(nodes):
        feature["properties"]["qa_layer"] = "drainage_nodes"
        features.append(feature)
    for feature in link_features(links):
        feature["properties"]["qa_layer"] = "drainage_links"
        features.append(feature)
    for feature in connection_features(connections):
        feature["properties"]["qa_layer"] = "surface_drainage_connections"
        features.append(feature)
    roads_path = ROOT / "data" / "roads" / "processed" / "bellandur_roads.geojson"
    if roads_path.exists():
        roads = load_json(roads_path)
        for feature in roads.get("features", []):
            feature["properties"] = {**feature.get("properties", {}), "qa_layer": "road_context", "source": "observed_osm"}
            features.append(feature)
    low_points_path = ROOT / "data" / "dem" / "terrain" / "low_points.geojson"
    if low_points_path.exists():
        low_points = load_json(low_points_path)
        for feature in low_points.get("features", []):
            feature["properties"] = {**feature.get("properties", {}), "qa_layer": "terrain_low_points", "source": "terrain_inferred", "context_only": True}
            features.append(feature)
    PREVIEW_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    write_geojson(PREVIEW_GEOJSON, "p4_bellandur_drainage_qa_context", features)


def connected_components(nodes: list[dict], links: list[dict]) -> list[list[str]]:
    adjacency: dict[str, set[str]] = {node["node_id"]: set() for node in nodes}
    for link in links:
        adjacency[link["from_node"]].add(link["to_node"])
        adjacency[link["to_node"]].add(link["from_node"])
    components = []
    unseen = set(adjacency)
    while unseen:
        start = min(unseen)
        queue = deque([start])
        unseen.remove(start)
        component = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbour in sorted(adjacency[current]):
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    queue.append(neighbour)
        components.append(sorted(component))
    return sorted(components, key=lambda component: component[0])


def validate_network(area: dict, nodes: list[dict], links: list[dict], connections: list[dict]) -> dict:
    area_bbox = bbox(area)
    node_ids = [node["node_id"] for node in nodes]
    link_ids = [link["link_id"] for link in links]
    node_set = set(node_ids)
    duplicate_node_ids = sorted([item for item, count in Counter(node_ids).items() if count > 1])
    duplicate_link_ids = sorted([item for item, count in Counter(link_ids).items() if count > 1])
    invalid_links = [link["link_id"] for link in links if link["from_node"] not in node_set or link["to_node"] not in node_set]
    self_loops = [link["link_id"] for link in links if link["from_node"] == link["to_node"]]
    invalid_geometry = [link["link_id"] for link in links if len(link["geometry"]) < 2 or any(not point_in_bbox(lon, lat, area_bbox) for lon, lat in link["geometry"])]
    invalid_direction = [link["link_id"] for link in links if link["direction"] not in {"forward_geometry_order"}]
    nodes_outside_bbox = [node["node_id"] for node in nodes if not point_in_bbox(node["lon"], node["lat"], area_bbox)]
    connection_errors = [item["connection_id"] for item in connections if item["drainage_node_id"] not in node_set]
    components = connected_components(nodes, links)
    degree = Counter()
    for link in links:
        degree[link["from_node"]] += 1
        degree[link["to_node"]] += 1
    orphan_nodes = sorted(node["node_id"] for node in nodes if degree[node["node_id"]] == 0)
    source_counts = Counter(node["source"] for node in nodes)
    link_source_counts = Counter(link["source"] for link in links)
    missing = {field: sum(1 for link in links if link.get(field) is None) for field in ("slope", "diameter_m", "capacity_m3s", "invert_elevation_m")}
    missing["node_invert_elevation_m"] = sum(1 for node in nodes if node.get("invert_elevation_m") is None)
    ground_valid = sum(1 for node in nodes if node.get("ground_elevation_m") is not None)
    checks = {
        "all_link_references_valid": not invalid_links,
        "unique_node_identifiers": not duplicate_node_ids,
        "unique_link_identifiers": not duplicate_link_ids,
        "no_unintended_self_loops": not self_loops,
        "link_geometry_valid_and_inside_bbox": not invalid_geometry,
        "link_direction_values_valid": not invalid_direction,
        "all_nodes_inside_canonical_bbox": not nodes_outside_bbox,
        "surface_connection_references_valid": not connection_errors,
        "all_nodes_have_provenance": all(bool(node.get("source")) for node in nodes),
        "all_links_have_provenance": all(bool(link.get("source")) for link in links),
        "all_ground_elevations_sampled_or_explicitly_missing": ground_valid == len(nodes),
    }
    return {
        "test_status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "node_count": len(nodes),
        "link_count": len(links),
        "connection_count": len(connections),
        "nodes_by_type": dict(sorted(Counter(node["node_type"] for node in nodes).items())),
        "links_by_type": dict(sorted(Counter(link["link_type"] for link in links).items())),
        "node_source_counts": dict(sorted(source_counts.items())),
        "link_source_counts": dict(sorted(link_source_counts.items())),
        "connected_components": {"count": len(components), "sizes": [len(component) for component in components], "members": components},
        "orphan_nodes": orphan_nodes,
        "unresolved_attributes": missing,
        "ground_elevation_sampled_nodes": ground_valid,
        "invalid_link_references": invalid_links,
        "duplicate_node_ids": duplicate_node_ids,
        "duplicate_link_ids": duplicate_link_ids,
        "self_loops": self_loops,
        "invalid_geometry": invalid_geometry,
        "invalid_direction": invalid_direction,
        "nodes_outside_bbox": nodes_outside_bbox,
        "invalid_connection_references": connection_errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-download", action="store_true", help="refresh the preserved OSM Overpass raw file")
    args = parser.parse_args()
    area = load_json(AREA_PATH)
    if area.get("crs") != PUBLIC_CRS:
        raise ValueError("The canonical study area must remain EPSG:4326")
    if not GOVERNMENT_KML.exists():
        raise FileNotFoundError(GOVERNMENT_KML)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if args.force_download or not OSM_RAW.exists():
        OSM_RAW.write_text(json.dumps(download_overpass(bbox(area)), indent=2) + "\n", encoding="utf-8")
    osm_payload = load_json(OSM_RAW)
    nodes, links, connections, acquisition_counts = build_network(area, osm_payload)
    acquisition_counts["government_clipped_link_count"] = sum(1 for link in links if link["source"] == "government_dataset")
    acquisition_counts["osm_clipped_link_count"] = sum(1 for link in links if link["source"] == "observed_osm")
    write_geojson(NODES_GEOJSON, "bellandur_drainage_nodes", node_features(nodes))
    write_geojson(LINKS_GEOJSON, "bellandur_drainage_links", link_features(links))
    write_geojson(CONNECTIONS_GEOJSON, "bellandur_surface_drainage_connections", connection_features(connections))
    write_graphml(nodes, links)
    build_preview(nodes, links, connections)
    validation = validate_network(area, nodes, links, connections)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    metadata = {
        "processing_script": SCRIPT_VERSION,
        "processing_date_utc": datetime.now(timezone.utc).isoformat(),
        "study_area_config": str(AREA_PATH.relative_to(ROOT)).replace("\\", "/"),
        "canonical_crs": PUBLIC_CRS,
        "working_crs": WORKING_CRS,
        "bbox": area["bbox"],
        "snap_tolerance_m": SNAP_TOLERANCE_M,
        "surface_connection_max_distance_m": CONNECTION_MAX_DISTANCE_M,
        "sources_investigated": [
            {"source": "government_dataset", "provider": "BBMP/KSRSAC via OpenCity.in", "url": "https://data.opencity.in/dataset/bengaluru-stormwater-drains-maps", "raw_file": str(GOVERNMENT_KML.relative_to(ROOT)).replace("\\", "/"), "classification": "observed government dataset", "license": "Public Domain as listed by OpenCity.in", "notes": "Combined 2022 primary/secondary/tertiary stormwater-drain KML; clipped to Bellandur."},
            {"source": "observed_osm", "provider": "OpenStreetMap contributors via Overpass API", "url": "https://www.openstreetmap.org/copyright", "overpass_url": OVERPASS_URL, "raw_file": str(OSM_RAW.relative_to(ROOT)).replace("\\", "/"), "classification": "observed open mapping data", "license": "ODbL; attribution required", "notes": "Waterway/drain/culvert ways and mapped manhole/inlet-like nodes."},
            {"source": "terrain_inferred", "provider": "Neer Kawach P2 terrain derivatives", "inputs": ["data/dem/terrain/flow_accumulation.tif", "data/dem/processed/bellandur_dem_buffered.tif"], "classification": "inferred candidate only", "notes": "Spaced high-flow-accumulation cells; not asserted to be real inlets or manholes."},
        ],
        "acquisition_counts": acquisition_counts,
        "outputs": {"nodes": str(NODES_GEOJSON.relative_to(ROOT)).replace("\\", "/"), "links": str(LINKS_GEOJSON.relative_to(ROOT)).replace("\\", "/"), "graphml": str(GRAPHML_PATH.relative_to(ROOT)).replace("\\", "/"), "surface_connections": str(CONNECTIONS_GEOJSON.relative_to(ROOT)).replace("\\", "/"), "qa_preview": str(PREVIEW_GEOJSON.relative_to(ROOT)).replace("\\", "/")},
        "schema": {"node_attributes": ["node_id", "node_type", "source", "latitude", "longitude", "x_m", "y_m", "ground_elevation_m", "invert_elevation_m", "capacity_m3s", "status", "metadata"], "link_attributes": ["link_id", "from_node", "to_node", "link_type", "source", "geometry", "length_m", "slope", "diameter_m", "width_m", "capacity_m3s", "invert_elevation_m", "direction_status", "metadata"]},
        "limitations": ["Mapped source line order is retained as an explicit graph direction but is not treated as verified hydraulic flow direction.", "No municipal underground pipe inventory, invert survey, capacity survey, or hydraulic observations were available in this P4 build.", "Ground elevations are DEM samples and must not be used as pipe invert elevations.", "Terrain-inferred candidates and surface connections are hypotheses only; no surface/drainage transfer is simulated.", "OSM waterway classes are preserved and are not assumed to be engineered stormwater drains."],
        "raw_source_sha256": {"government_kml": sha256(GOVERNMENT_KML), "osm_overpass_json": sha256(OSM_RAW)},
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    VALIDATION_PATH.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"metadata": metadata, "validation": validation}, indent=2))


if __name__ == "__main__":
    main()
