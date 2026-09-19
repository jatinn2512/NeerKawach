"""P8 flood-aware routing over the existing directed OSM road graph.

This module is downstream-only. It reads the P1 road GraphML/GeoJSON and P7
road-impact products; it does not modify P1-P7 data or run any flood model.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "routing.json"
STUDY_AREA_PATH = ROOT / "config" / "study_area.json"
SCRIPT_VERSION = "p8-routing-1.0.0"
EARTH_RADIUS_M = 6_371_008.8


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def timestamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def haversine_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return EARTH_RADIUS_M * 2.0 * math.asin(math.sqrt(a))


def parse_wkt_linestring(value: str | None, source: tuple[float, float], target: tuple[float, float]) -> list[tuple[float, float]]:
    if not value:
        return [source, target]
    text = " ".join(value.replace("\n", " ").split())
    if not text.upper().startswith("LINESTRING"):
        return [source, target]
    body = text[text.find("(") + 1:text.rfind(")")]
    points: list[tuple[float, float]] = []
    for item in body.split(","):
        parts = item.strip().split()
        if len(parts) >= 2:
            points.append((float(parts[0]), float(parts[1])))
    return points if len(points) >= 2 else [source, target]


def polyline_length_m(geometry: list[tuple[float, float]]) -> float:
    return sum(haversine_m(first, second) for first, second in zip(geometry, geometry[1:]))


@dataclass(frozen=True)
class Edge:
    edge_id: str
    source: str
    target: str
    osm_way_id: str
    road_id: str
    highway: str
    name: str
    oneway: str
    maxspeed: str
    geometry: tuple[tuple[float, float], ...]
    length_m: float


@dataclass
class RoadGraph:
    nodes: dict[str, tuple[float, float]]
    edges: dict[str, Edge]
    outgoing: dict[str, list[str]]
    source_file: Path


@dataclass(frozen=True)
class Impact:
    road_id: str
    timestamp: str
    depth_m: float | None
    affected: bool | None
    risk_class: str
    source_raster: str


@dataclass
class P7Impacts:
    by_key: dict[tuple[str, str], Impact]
    summary_by_road: dict[str, dict[str, str]]
    timestamps: tuple[str, ...]
    timeseries_file: Path
    summary_file: Path


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def load_graph(path: Path) -> RoadGraph:
    root = ET.parse(path).getroot()
    nodes: dict[str, tuple[float, float]] = {}
    for node in root.iter():
        if xml_local_name(node.tag) != "node":
            continue
        values = {str(child.attrib.get("key", "")): child.text or "" for child in node}
        try:
            nodes[str(node.attrib["id"])] = (float(values["x"]), float(values["y"]))
        except (KeyError, ValueError) as error:
            raise ValueError(f"Invalid GraphML node: {node.attrib.get('id')}") from error
    edges: dict[str, Edge] = {}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in root.iter():
        if xml_local_name(edge.tag) != "edge":
            continue
        values = {xml_local_name(child.attrib.get("key", "")): child.text or "" for child in edge}
        edge_id = str(edge.attrib["id"])
        source = str(edge.attrib["source"])
        target = str(edge.attrib["target"])
        if source not in nodes or target not in nodes:
            raise ValueError(f"GraphML edge {edge_id} references a missing node")
        osm_way_id = str(values.get("osm_way_id", ""))
        if not osm_way_id:
            raise ValueError(f"GraphML edge {edge_id} has no OSM way identifier")
        geometry = parse_wkt_linestring(values.get("geometry"), nodes[source], nodes[target])
        item = Edge(
            edge_id=edge_id,
            source=source,
            target=target,
            osm_way_id=osm_way_id,
            road_id=f"way/{osm_way_id}",
            highway=values.get("highway", ""),
            name=values.get("name", ""),
            oneway=values.get("oneway", ""),
            maxspeed=values.get("maxspeed", ""),
            geometry=tuple(geometry),
            length_m=polyline_length_m(geometry),
        )
        if edge_id in edges:
            raise ValueError(f"Duplicate GraphML edge identifier: {edge_id}")
        edges[edge_id] = item
        outgoing.setdefault(source, []).append(edge_id)
    for node_id in outgoing:
        outgoing[node_id].sort()
    if not nodes or not edges:
        raise ValueError("Routing graph is empty")
    return RoadGraph(nodes=nodes, edges=edges, outgoing=outgoing, source_file=path)


def load_p7_impacts(timeseries_path: Path, summary_path: Path) -> P7Impacts:
    by_key: dict[tuple[str, str], Impact] = {}
    with timeseries_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            road_id = str(row.get("road_id", ""))
            timestamp = str(row.get("timestamp", ""))
            if not road_id or not timestamp:
                raise ValueError("P7 road time series contains a row without road_id or timestamp")
            parse_timestamp(timestamp)
            key = (road_id, timestamp)
            if key in by_key:
                raise ValueError(f"Duplicate P7 road-impact record: {key}")
            depth = finite_float(row.get("max_intersecting_depth_m"))
            affected_text = str(row.get("affected", "")).strip().lower()
            affected = None if not affected_text else affected_text == "true"
            by_key[key] = Impact(road_id, timestamp, depth, affected, str(row.get("risk_class", "")), str(row.get("source_raster", "")))
    summary_by_road: dict[str, dict[str, str]] = {}
    with summary_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            road_id = str(row.get("road_id", ""))
            if not road_id:
                raise ValueError("P7 road summary contains a row without road_id")
            if road_id in summary_by_road:
                raise ValueError(f"Duplicate P7 road-summary record: {road_id}")
            summary_by_road[road_id] = dict(row)
    timestamps = tuple(sorted({key[1] for key in by_key}, key=parse_timestamp))
    if not timestamps:
        raise ValueError("P7 road-impact time series is empty")
    return P7Impacts(by_key, summary_by_road, timestamps, timeseries_path, summary_path)


def validate_config(config: dict[str, Any], p7_config: dict[str, Any]) -> None:
    flooded = float(config["flooded_threshold_m"])
    closure = float(config["closure_threshold_m"])
    if flooded <= 0 or closure <= flooded:
        raise ValueError("P8 thresholds must satisfy 0 < flooded_threshold_m < closure_threshold_m")
    if abs(flooded - float(p7_config["depth_threshold_m"])) > 1e-9:
        raise ValueError("P8 flooded threshold must match the P7 inundation threshold")
    if float(config["flood_penalty_factor"]) < 0:
        raise ValueError("P8 flood penalty factor cannot be negative")
    if float(config["snap_tolerance_m"]) <= 0:
        raise ValueError("P8 snap tolerance must be positive")


def classify_depth(depth_m: float | None, config: dict[str, Any]) -> str:
    if depth_m is None:
        return "data_unavailable"
    if depth_m < float(config["flooded_threshold_m"]):
        return "normal"
    if depth_m < float(config["closure_threshold_m"]):
        return "flooded_traversable"
    return "closed"


class RoutingEngine:
    def __init__(self, config: dict[str, Any], study_area: dict[str, Any], graph: RoadGraph, impacts: P7Impacts):
        self.config = config
        self.study_area = study_area
        self.graph = graph
        self.impacts = impacts
        self.p7_by_road = impacts.summary_by_road
        self.road_ids = {edge.road_id for edge in graph.edges.values()}

    def validate_join(self) -> dict[str, Any]:
        graph_road_ids = sorted(self.road_ids)
        p7_road_ids = set(self.p7_by_road)
        missing_summary = sorted(set(graph_road_ids) - p7_road_ids)
        timeseries_roads = {road_id for road_id, _ in self.impacts.by_key}
        missing_timeseries = sorted(set(graph_road_ids) - timeseries_roads)
        return {
            "graph_edge_count": len(self.graph.edges),
            "graph_node_count": len(self.graph.nodes),
            "graph_road_id_count": len(graph_road_ids),
            "p7_summary_road_count": len(p7_road_ids),
            "p7_timeseries_road_count": len(timeseries_roads),
            "missing_summary_road_ids": missing_summary,
            "missing_timeseries_road_ids": missing_timeseries,
            "complete_for_graph": not missing_summary and not missing_timeseries,
        }

    def impact_for(self, edge: Edge, timestamp: str) -> Impact | None:
        return self.impacts.by_key.get((edge.road_id, timestamp))

    def edge_state(self, edge: Edge, timestamp: str) -> str:
        impact = self.impact_for(edge, timestamp)
        return classify_depth(impact.depth_m if impact else None, self.config)

    def edge_cost(self, edge: Edge, timestamp: str, flood_aware: bool) -> float | None:
        if not flood_aware:
            return edge.length_m
        impact = self.impact_for(edge, timestamp)
        state = classify_depth(impact.depth_m if impact else None, self.config)
        if state in {"closed", "data_unavailable"}:
            return None
        if state == "normal":
            return edge.length_m
        depth = float(impact.depth_m)
        closure = float(self.config["closure_threshold_m"])
        penalty = float(self.config["flood_penalty_factor"])
        return edge.length_m * (1.0 + penalty * depth / closure)

    def snap_point(self, point: tuple[float, float]) -> tuple[str, float]:
        nearest = min(self.graph.nodes, key=lambda node_id: (haversine_m(point, self.graph.nodes[node_id]), node_id))
        distance = haversine_m(point, self.graph.nodes[nearest])
        if distance > float(self.config["snap_tolerance_m"]):
            raise ValueError(f"Point is {distance:.2f} m from the nearest road node, beyond snap tolerance")
        return nearest, distance

    def _shortest_path(self, source: str, target: str, timestamp: str, flood_aware: bool) -> list[str] | None:
        distances = {source: 0.0}
        previous: dict[str, tuple[str, str]] = {}
        queue: list[tuple[float, str]] = [(0.0, source)]
        while queue:
            distance, node_id = heapq.heappop(queue)
            if distance > distances.get(node_id, math.inf) + 1e-9:
                continue
            if node_id == target:
                break
            for edge_id in self.graph.outgoing.get(node_id, []):
                edge = self.graph.edges[edge_id]
                cost = self.edge_cost(edge, timestamp, flood_aware)
                if cost is None:
                    continue
                candidate = distance + cost
                if candidate < distances.get(edge.target, math.inf) - 1e-9:
                    distances[edge.target] = candidate
                    previous[edge.target] = (node_id, edge_id)
                    heapq.heappush(queue, (candidate, edge.target))
        if target not in distances:
            return None
        path: list[str] = []
        current = target
        while current != source:
            previous_node, edge_id = previous[current]
            path.append(edge_id)
            current = previous_node
        path.reverse()
        return path

    def _path_metrics(self, path: list[str] | None, timestamp: str, flood_aware: bool) -> dict[str, Any]:
        if path is None:
            return {"edge_ids": [], "distance_m": None, "route_cost": None, "maximum_depth_m": None, "affected_segments": [], "closed_segments": [], "data_unavailable_segments": []}
        depths: list[float] = []
        affected: list[str] = []
        closed: list[str] = []
        unavailable: list[str] = []
        cost = 0.0
        distance = 0.0
        for edge_id in path:
            edge = self.graph.edges[edge_id]
            impact = self.impact_for(edge, timestamp)
            state = classify_depth(impact.depth_m if impact else None, self.config)
            edge_cost = self.edge_cost(edge, timestamp, flood_aware)
            if edge_cost is not None:
                cost += edge_cost
            distance += edge.length_m
            if impact and impact.depth_m is not None:
                depths.append(impact.depth_m)
            if state in {"flooded_traversable", "closed"}:
                affected.append(edge_id)
            if state == "closed":
                closed.append(edge_id)
            if state == "data_unavailable":
                unavailable.append(edge_id)
        return {
            "edge_ids": path,
            "distance_m": distance,
            "route_cost": cost,
            "maximum_depth_m": max(depths) if depths else None,
            "affected_segments": affected,
            "closed_segments": closed,
            "data_unavailable_segments": unavailable,
        }

    def route(self, origin: tuple[float, float], destination: tuple[float, float], timestamp: str) -> dict[str, Any]:
        if timestamp not in self.impacts.timestamps:
            raise ValueError(f"Timestamp is not present in P7 road-impact time series: {timestamp}")
        origin_node, origin_snap_m = self.snap_point(origin)
        destination_node, destination_snap_m = self.snap_point(destination)
        baseline_path = self._shortest_path(origin_node, destination_node, timestamp, False)
        flood_path = self._shortest_path(origin_node, destination_node, timestamp, True) if baseline_path is not None else None
        baseline = self._path_metrics(baseline_path, timestamp, False)
        flood = self._path_metrics(flood_path, timestamp, True)
        baseline_affected = set(baseline["affected_segments"])
        flood_edges = set(flood["edge_ids"])
        if baseline_path is None:
            status = "no_route"
        elif flood_path is None:
            status = "no_flood_aware_route"
        else:
            status = "ok"
        return {
            "status": status,
            "timestamp": timestamp,
            "origin": {"longitude": origin[0], "latitude": origin[1]},
            "destination": {"longitude": destination[0], "latitude": destination[1]},
            "snapped_origin": {"node_id": origin_node, "distance_m": origin_snap_m},
            "snapped_destination": {"node_id": destination_node, "distance_m": destination_snap_m},
            "baseline": baseline,
            "flood_aware": flood,
            "avoided_flooded_segments": sorted(baseline_affected - flood_edges),
            "source_phase": "P8",
        }

    def _path_geometry(self, edge_ids: list[str]) -> list[list[float]]:
        coordinates: list[list[float]] = []
        for edge_id in edge_ids:
            for point in self.graph.edges[edge_id].geometry:
                item = [float(point[0]), float(point[1])]
                if not coordinates or coordinates[-1] != item:
                    coordinates.append(item)
        return coordinates

    def to_geojson(self, result: dict[str, Any]) -> dict[str, Any]:
        features = []
        for route_name in ("baseline", "flood_aware"):
            route = result[route_name]
            if not route["edge_ids"]:
                continue
            features.append({
                "type": "Feature",
                "id": route_name,
                "properties": {
                    "route_type": route_name,
                    "status": result["status"],
                    "timestamp": result["timestamp"],
                    "distance_m": route["distance_m"],
                    "route_cost": route["route_cost"],
                    "maximum_depth_m": route["maximum_depth_m"],
                    "affected_segment_count": len(route["affected_segments"]),
                    "source_phase": "P8",
                },
                "geometry": {"type": "LineString", "coordinates": self._path_geometry(route["edge_ids"])},
            })
        return {
            "type": "FeatureCollection",
            "name": "floodops_p8_route_comparison",
            "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
            "properties": {"source_phase": "P8", "timestamp": result["timestamp"], "study_area": self.study_area},
            "features": features,
        }


def create_engine() -> RoutingEngine:
    config = load_json(CONFIG_PATH)
    study_area = load_json(STUDY_AREA_PATH)
    p7_config = load_json(ROOT / config["source_p7_config"])
    validate_config(config, p7_config)
    graph = load_graph(ROOT / config["source_road_graph"])
    impacts = load_p7_impacts(ROOT / config["source_p7_road_timeseries"], ROOT / config["source_p7_road_summary"])
    engine = RoutingEngine(config, study_area, graph, impacts)
    join = engine.validate_join()
    if not join["complete_for_graph"]:
        raise ValueError("P7 road-impact join is incomplete for the routing graph; missing values are not inferred")
    return engine


def write_outputs(engine: RoutingEngine, result: dict[str, Any], stem: str = "route") -> dict[str, str]:
    output_config = engine.config["outputs"]
    route_dir = ROOT / output_config["route_directory"]
    metrics_dir = ROOT / output_config["metrics_directory"]
    metadata_dir = ROOT / output_config["metadata_directory"]
    for directory in (route_dir, metrics_dir, metadata_dir):
        directory.mkdir(parents=True, exist_ok=True)
    safe_timestamp = result["timestamp"].replace(":", "").replace("-", "")
    prefix = f"{stem}_{safe_timestamp}"
    geojson_path = route_dir / f"{prefix}.geojson"
    metrics_path = metrics_dir / f"{prefix}.json"
    provenance_path = metadata_dir / f"{prefix}_provenance.json"
    provenance = {
        "processing_script": SCRIPT_VERSION,
        "generated_at_utc": timestamp_text(datetime.now(timezone.utc)),
        "source_road_graph": relative(engine.graph.source_file),
        "source_p7_road_timeseries": relative(engine.impacts.timeseries_file),
        "source_p7_road_summary": relative(engine.impacts.summary_file),
        "study_area_config": relative(STUDY_AREA_PATH),
        "study_area": engine.study_area,
        "routing_config": relative(CONFIG_PATH),
        "routing_configuration": engine.config,
        "timestamp": result["timestamp"],
        "join_validation": engine.validate_join(),
        "source_phase": "P8",
    }
    geojson_path.write_text(json.dumps(engine.to_geojson(result), indent=2) + "\n", encoding="utf-8")
    metrics_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return {"geojson": relative(geojson_path), "metrics": relative(metrics_path), "provenance": relative(provenance_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin-lat", type=float, required=True)
    parser.add_argument("--origin-lon", type=float, required=True)
    parser.add_argument("--destination-lat", type=float, required=True)
    parser.add_argument("--destination-lon", type=float, required=True)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--output-stem", default="route")
    args = parser.parse_args()
    engine = create_engine()
    result = engine.route((args.origin_lon, args.origin_lat), (args.destination_lon, args.destination_lat), args.timestamp)
    outputs = write_outputs(engine, result, args.output_stem)
    print(json.dumps({"result": result, "outputs": outputs}, indent=2))


if __name__ == "__main__":
    main()
