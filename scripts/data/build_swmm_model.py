"""Generate the maximum defensible P4-derived EPA SWMM model for P5.

Every P4 component containing valid drainage links is represented in the same
SWMM input without adding links between components. The sole P4 outfall is
retained. Linked components without a verified outfall use explicitly labelled
closed terminal junction boundaries; isolated terrain candidates remain
excluded because they have no P4 hydraulic link to represent.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rasterio.warp import transform as project_points


ROOT = Path(__file__).resolve().parents[2]
AREA_PATH = ROOT / "config" / "study_area.json"
CONFIG_PATH = ROOT / "config" / "swmm_model.json"
NODES_PATH = ROOT / "data" / "drainage" / "processed" / "drainage_nodes.geojson"
LINKS_PATH = ROOT / "data" / "drainage" / "processed" / "drainage_links.geojson"
STORM_PATH = ROOT / "data" / "swmm" / "tests" / "synthetic_storm.json"
MODEL_DIR = ROOT / "data" / "swmm" / "models"
MODEL_PATH = MODEL_DIR / "bellandur_prototype.inp"
METADATA_DIR = ROOT / "data" / "swmm" / "metadata"
METADATA_PATH = METADATA_DIR / "component_assessment.json"
MAPPING_PATH = METADATA_DIR / "p4_to_swmm_mapping.json"
COVERAGE_PATH = METADATA_DIR / "subcatchment_coverage.json"
SUBCATCHMENT_GEOJSON_PATH = METADATA_DIR / "subcatchments.geojson"
SCRIPT_VERSION = "p5-swmm-model-builder-2.1.0"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def components(node_ids: list[str], links: list[dict]) -> list[list[str]]:
    adjacency = {node_id: set() for node_id in node_ids}
    for link in links:
        if link["from_node"] in adjacency and link["to_node"] in adjacency:
            adjacency[link["from_node"]].add(link["to_node"])
            adjacency[link["to_node"]].add(link["from_node"])
    unseen = set(adjacency)
    result = []
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
        result.append(sorted(component))
    return sorted(result, key=lambda item: item[0])


def parse_storm(path: Path) -> dict:
    storm = load_json(path)
    records = storm.get("records", [])
    if storm.get("source") != "synthetic_test":
        raise ValueError("P5 fixture must remain explicitly labelled synthetic_test")
    timestep = float(storm.get("timestep_seconds", 0))
    if timestep <= 0 or storm.get("units") != "mm_per_timestep" or not records:
        raise ValueError("Synthetic storm requires positive timestep, mm_per_timestep units and records")
    for record in records:
        value = record.get("rainfall_mm")
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError("Synthetic storm rainfall must be finite and non-negative")
    return storm


def dt_parts(timestamp: str) -> tuple[str, str]:
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return value.strftime("%m/%d/%Y"), value.strftime("%H:%M")


def fmt(value: float | int | None) -> str:
    if value is None:
        return "0"
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def project_lonlat(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    xs, ys = project_points("EPSG:4326", "EPSG:32643", lons, lats)
    return list(zip(xs, ys))


def polygon_area(points: list[tuple[float, float]]) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:])) / 2.0)


def make_subcatchments(area: dict, nodes: dict, junction_ids: list[str], assumptions: dict, component_by_node: dict) -> tuple[list[dict], dict, dict]:
    bbox = area["bbox"]
    west, east = float(bbox["min_lon"]), float(bbox["max_lon"])
    south, north = float(bbox["min_lat"]), float(bbox["max_lat"])
    target_cell_m = float(assumptions["prototype_subcatchment_grid_cell_size_m"])
    if target_cell_m <= 0:
        raise ValueError("prototype_subcatchment_grid_cell_size_m must be positive")
    east_west_m = math.dist(project_lonlat([(west, south), (east, south)])[0], project_lonlat([(west, south), (east, south)])[1])
    north_south_m = math.dist(project_lonlat([(west, south), (west, north)])[0], project_lonlat([(west, south), (west, north)])[1])
    columns = max(1, math.ceil(east_west_m / target_cell_m))
    rows = max(1, math.ceil(north_south_m / target_cell_m))
    junction_points = {node_id: (float(nodes[node_id]["coordinates"][0]), float(nodes[node_id]["coordinates"][1])) for node_id in junction_ids}
    junction_xy = {node_id: project_lonlat([point])[0] for node_id, point in junction_points.items()}
    cells = []
    features = []
    for row in range(rows):
        lat0 = south + (north - south) * row / rows
        lat1 = south + (north - south) * (row + 1) / rows
        for column in range(columns):
            lon0 = west + (east - west) * column / columns
            lon1 = west + (east - west) * (column + 1) / columns
            polygon_lonlat = [(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1), (lon0, lat0)]
            polygon_xy = project_lonlat(polygon_lonlat)
            area_m2 = polygon_area(polygon_xy)
            centroid = ((lon0 + lon1) / 2.0, (lat0 + lat1) / 2.0)
            centroid_xy = project_lonlat([centroid])[0]
            outlet_node_id = min(junction_ids, key=lambda node_id: math.dist(centroid_xy, junction_xy[node_id]))
            distance_m = math.dist(centroid_xy, junction_xy[outlet_node_id])
            subcatchment_id = f"SC{len(cells) + 1:03d}"
            cells.append({"subcatchment_id": subcatchment_id, "row": row, "column": column, "area_m2": area_m2, "area_ha": area_m2 / 10000.0, "centroid_lon": centroid[0], "centroid_lat": centroid[1], "outlet_node_id": outlet_node_id, "outlet_component_id": component_by_node[outlet_node_id], "routing_source": "prototype_subcatchment", "routing_method": "nearest_P4_simulated_junction_centroid", "verified_drainage_connection": False, "prototype_boundary_source": "model_assumption", "centroid_to_outlet_distance_m": distance_m, "geometry": polygon_lonlat})
            features.append({"type": "Feature", "id": subcatchment_id, "properties": {key: value for key, value in cells[-1].items() if key != "geometry"}, "geometry": {"type": "Polygon", "coordinates": [[list(point) for point in polygon_lonlat]]}})
    boundary = []
    boundary.extend((west + (east - west) * column / columns, south) for column in range(columns + 1))
    boundary.extend((east, south + (north - south) * row / rows) for row in range(1, rows + 1))
    boundary.extend((west + (east - west) * column / columns, north) for column in range(columns - 1, -1, -1))
    boundary.extend((west, south + (north - south) * row / rows) for row in range(rows - 1, 0, -1))
    boundary.append(boundary[0])
    canonical_area_m2 = polygon_area(project_lonlat(boundary))
    modeled_area_m2 = sum(cell["area_m2"] for cell in cells)
    area_residual_m2 = canonical_area_m2 - modeled_area_m2
    residual_fraction = abs(area_residual_m2) / canonical_area_m2 if canonical_area_m2 else 1.0
    if residual_fraction > float(assumptions["full_area_max_residual_fraction"]):
        raise ValueError(f"Subcatchment tiling residual is materially large: {residual_fraction:.6f}")
    if modeled_area_m2 / canonical_area_m2 < float(assumptions["full_area_min_coverage_fraction"]):
        raise ValueError("Subcatchment coverage is materially incomplete")
    coverage = {
        "processing_script": SCRIPT_VERSION,
        "canonical_study_area_config": "config/study_area.json",
        "canonical_bbox": bbox,
        "canonical_crs": area.get("crs"),
        "working_crs": "EPSG:32643",
        "configured_approximate_area_km2": float(area["approximate_area_km2"]),
        "canonical_bbox_area_m2_projected": canonical_area_m2,
        "canonical_bbox_area_km2_projected": canonical_area_m2 / 1e6,
        "modeled_subcatchment_area_m2": modeled_area_m2,
        "modeled_subcatchment_area_km2": modeled_area_m2 / 1e6,
        "modeled_subcatchment_area_ha": modeled_area_m2 / 10000.0,
        "coverage_percentage": modeled_area_m2 / canonical_area_m2 * 100.0,
        "subcatchment_count": len(cells),
        "grid": {"target_cell_size_m": target_cell_m, "rows": rows, "columns": columns, "deterministic_geometry": "regular EPSG:4326 bbox grid; each cell projected to EPSG:32643 for area and nearest-node distance"},
        "area_statistics": {"minimum_m2": min(cell["area_m2"] for cell in cells), "maximum_m2": max(cell["area_m2"] for cell in cells), "mean_m2": modeled_area_m2 / len(cells), "minimum_ha": min(cell["area_ha"] for cell in cells), "maximum_ha": max(cell["area_ha"] for cell in cells)},
        "gaps": {"gap_area_m2": max(0.0, area_residual_m2), "gap_fraction": max(0.0, area_residual_m2) / canonical_area_m2, "material_gap": False, "method": "grid cells tile the canonical bbox; residual is projected polygon rounding"},
        "overlaps": {"overlap_area_m2": max(0.0, -area_residual_m2), "overlap_fraction": max(0.0, -area_residual_m2) / canonical_area_m2, "material_overlap": False, "method": "disjoint row/column intervals generate shared boundaries only"},
        "routing_strategy": "Every full-area prototype subcatchment routes lateral runoff directly to its nearest existing P4 simulated junction by centroid distance. This is a prototype runoff allocation and does not create a municipal pipe, link, outfall, or verified drainage connection.",
        "routing_source": "prototype_subcatchment",
        "subcatchments": cells,
    }
    geojson = {"type": "FeatureCollection", "name": "p5_full_area_prototype_subcatchments", "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}, "features": features}
    return cells, coverage, geojson


def feature_geometry_valid(feature: dict) -> bool:
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates")
    return geometry.get("type") == "LineString" and isinstance(coordinates, list) and len(coordinates) >= 2 and all(isinstance(point, list) and len(point) >= 2 for point in coordinates)


def component_audit(component_id: str, component: list[str], component_links: list[dict], nodes: dict, outfall_id: str | None) -> dict:
    degree = Counter()
    for link in component_links:
        degree[link["from_node"]] += 1
        degree[link["to_node"]] += 1
    node_features = [nodes[node_id] for node_id in component]
    linked = bool(component_links)
    contains_outfall = outfall_id in component if outfall_id else False
    terrain_orphans = sorted(node_id for node_id in component if nodes[node_id].get("source") == "terrain_inferred")
    valid_geometry = all(feature_geometry_valid(link) for link in component_links) if linked else None
    valid_references = all(link["from_node"] in component and link["to_node"] in component for link in component_links) if linked else None
    if linked and valid_geometry and valid_references:
        status = "simulated"
        exclusion_reason = None
        suitable = True
        boundary_type = "verified_outfall" if contains_outfall else "closed_terminal_junction"
        boundary_nodes = [outfall_id] if contains_outfall else sorted(node_id for node_id in component if degree[node_id] == 1)
        if not boundary_nodes:
            boundary_nodes = [component[0]]
    elif terrain_orphans and not linked:
        status = "excluded"
        exclusion_reason = "isolated terrain-inferred candidate; no P4 hydraulic link or verified outfall"
        suitable = False
        boundary_type = None
        boundary_nodes = []
    elif not linked:
        status = "excluded"
        exclusion_reason = "no usable P4 drainage link"
        suitable = False
        boundary_type = None
        boundary_nodes = []
    else:
        status = "excluded"
        exclusion_reason = "invalid P4 geometry or endpoint topology"
        suitable = False
        boundary_type = None
        boundary_nodes = []
    return {
        "component_id": component_id,
        "node_ids": component,
        "link_ids": [link["link_id"] for link in component_links],
        "node_count": len(component),
        "link_count": len(component_links),
        "node_types": dict(sorted(Counter(nodes[node_id].get("node_type", "unknown") for node_id in component).items())),
        "link_types": dict(sorted(Counter(link.get("link_type", "unknown") for link in component_links).items())),
        "provenance": {
            "node_sources": dict(sorted(Counter(nodes[node_id].get("source", "unknown") for node_id in component).items())),
            "link_sources": dict(sorted(Counter(link.get("source", "unknown") for link in component_links).items())),
        },
        "contains_outfall_candidate": contains_outfall,
        "terrain_inferred_orphan_nodes": terrain_orphans,
        "orphan_node_count": len(terrain_orphans),
        "geometric_continuity": {
            "valid_line_geometries": valid_geometry,
            "endpoint_node_references_valid": valid_references,
            "basis": "P4 link endpoint identifiers and valid LineString geometries; no inter-component geometry was created." if linked else "Not applicable: component contains no P4 link geometry.",
        },
        "suitable_for_hydraulic_simulation": suitable,
        "status": status,
        "boundary_type": boundary_type,
        "boundary_node_ids": boundary_nodes,
        "boundary_source": "observed_source_backed" if boundary_type == "verified_outfall" else ("model_assumption" if boundary_type else None),
        "exclusion_reason": exclusion_reason,
    }


def build_model() -> dict:
    config = load_json(CONFIG_PATH)
    area = load_json(AREA_PATH)
    previous_coverage = load_json(COVERAGE_PATH) if COVERAGE_PATH.exists() else {}
    if area.get("crs") != "EPSG:4326":
        raise ValueError("Canonical study area must remain EPSG:4326")
    node_features = load_json(NODES_PATH)["features"]
    link_features = load_json(LINKS_PATH)["features"]
    storm = parse_storm(STORM_PATH)
    nodes = {feature["properties"]["node_id"]: feature["properties"] | {"coordinates": feature["geometry"]["coordinates"], "geometry": feature["geometry"]} for feature in node_features}
    links = [feature["properties"] | {"coordinates": feature["geometry"]["coordinates"], "geometry": feature["geometry"]} for feature in link_features]
    node_ids = sorted(nodes)
    graph_components = components(node_ids, links)
    outfall_candidates = [node_id for node_id, node in nodes.items() if node.get("node_type") == "outfall" and node.get("status") == "outfall_candidate"]
    if len(outfall_candidates) != 1:
        raise ValueError(f"Expected exactly one P4 outfall candidate, found {outfall_candidates}")
    outfall_id = outfall_candidates[0]
    component_by_node = {}
    assessments = []
    for index, component in enumerate(graph_components, start=1):
        component_id = f"component_{index:03d}"
        for node_id in component:
            component_by_node[node_id] = component_id
        component_links = [link for link in links if link["from_node"] in component and link["to_node"] in component]
        assessments.append(component_audit(component_id, component, component_links, nodes, outfall_id))
    simulated_assessments = [item for item in assessments if item["status"] == "simulated"]
    simulated_node_ids = sorted(node_id for item in simulated_assessments for node_id in item["node_ids"])
    simulated_link_ids = sorted(link_id for item in simulated_assessments for link_id in item["link_ids"])
    simulated_link_set = set(simulated_link_ids)
    simulated_links = [link for link in links if link["link_id"] in simulated_link_set]
    assumptions = config["model_assumptions"]
    if assumptions.get("source") != "model_assumption":
        raise ValueError("All P5 hydraulic defaults must be under source=model_assumption")
    invert_offset = float(assumptions["invert_offset_below_ground_m"])
    for node_id in simulated_node_ids:
        if nodes[node_id].get("ground_elevation_m") is None:
            raise ValueError(f"P4 node {node_id} has no ground elevation for the model assumption")

    model_links = []
    direction_adjustments = []
    for link in sorted(simulated_links, key=lambda item: item["link_id"]):
        model_link = dict(link)
        if model_link["from_node"] == outfall_id and model_link["to_node"] != outfall_id:
            model_link["from_node"], model_link["to_node"] = model_link["to_node"], model_link["from_node"]
            direction_adjustments.append({"link_id": link["link_id"], "reason": "reversed so the P4 outfall candidate is the downstream terminal node", "source_direction": f"{link['from_node']}->{link['to_node']}", "model_direction": f"{model_link['from_node']}->{model_link['to_node']}", "source": "model_assumption"})
        model_links.append(model_link)
    model_link_by_id = {link["link_id"]: link for link in model_links}

    start_date, start_time = dt_parts(storm["records"][0]["timestamp"])
    end_date_time = datetime.fromisoformat(storm["records"][-1]["timestamp"].replace("Z", "+00:00")) + timedelta(seconds=float(storm["timestep_seconds"]))
    end_date, end_time = end_date_time.strftime("%m/%d/%Y"), end_date_time.strftime("%H:%M")
    junctions = [nodes[node_id] for node_id in simulated_node_ids if node_id != outfall_id]
    subcatchments, coverage, subcatchment_geojson = make_subcatchments(area, nodes, [node["node_id"] for node in junctions], assumptions, component_by_node)
    lines = [
        "; FloodOps P5 maximum defensible P4 network — generated, not observed BBMP infrastructure",
        "; All valid P4 linked components are retained; no inter-component links are fabricated.",
        "; Closed terminal junction boundaries and hydraulic parameters are model_assumption values.",
        "[TITLE]",
        ";;Bellandur prototype hydraulic simulation",
        "",
        "[OPTIONS]",
        "FLOW_UNITS CMS",
        "INFILTRATION HORTON",
        "FLOW_ROUTING DYNWAVE",
        f"START_DATE {start_date}",
        f"START_TIME {start_time}",
        f"REPORT_START_DATE {start_date}",
        f"REPORT_START_TIME {start_time}",
        f"END_DATE {end_date}",
        f"END_TIME {end_time}",
        "REPORT_STEP 00:05:00",
        f"WET_STEP 00:00:{int(config['routing']['hydraulic_timestep_seconds']):02d}",
        f"ROUTING_STEP 00:00:{int(config['routing']['hydraulic_timestep_seconds']):02d}",
        "ALLOW_PONDING YES" if config["routing"]["allow_ponding"] else "ALLOW_PONDING NO",
        "",
        "[EVAPORATION]",
        "CONSTANT 0",
        "",
        "[RAINGAGES]",
        ";;Name Format Interval SCF Source",
        "GAGE1 INTENSITY 00:05 1.0 TIMESERIES SyntheticStorm",
        "",
        "[SUBCATCHMENTS]",
        ";;Name RainGage Outlet Area(ha) %Imperv Width(m) %Slope CurbLen SnowPack",
    ]
    for subcatchment in subcatchments:
        lines.append(f"{subcatchment['subcatchment_id']} GAGE1 {subcatchment['outlet_node_id']} {fmt(subcatchment['area_ha'])} {fmt(assumptions['impervious_percent'])} {fmt(assumptions['subcatchment_width_m'])} {fmt(assumptions['subcatchment_slope_percent'])} 0")
    lines.extend(["", "[SUBAREAS]", ";;Subcatchment N-Imperv N-Perv S-Imperv S-Perv PctZero RouteTo PctRouted"])
    for subcatchment in subcatchments:
        lines.append(f"{subcatchment['subcatchment_id']} {fmt(assumptions['impervious_roughness_n'])} {fmt(assumptions['pervious_roughness_n'])} {fmt(assumptions['impervious_storage_mm'])} {fmt(assumptions['pervious_storage_mm'])} {fmt(assumptions['percent_zero_impervious'])} OUTLET 100")
    lines.extend(["", "[INFILTRATION]", ";;Subcatchment MaxRate MinRate Decay DryTime MaxInfil"])
    for subcatchment in subcatchments:
        lines.append(f"{subcatchment['subcatchment_id']} {fmt(assumptions['horton_max_rate_mm_per_hour'])} {fmt(assumptions['horton_min_rate_mm_per_hour'])} {fmt(assumptions['horton_decay_per_hour'])} {fmt(assumptions['horton_dry_time_hours'])}")
    lines.extend(["", "[JUNCTIONS]", ";;Name Elevation Ymax Y0 Ysur Apond"])
    for node in junctions:
        invert = float(node["ground_elevation_m"]) - invert_offset
        lines.append(f"{node['node_id']} {fmt(invert)} {fmt(assumptions['junction_max_depth_m'])} {fmt(assumptions['junction_initial_depth_m'])} {fmt(assumptions['junction_surcharge_depth_m'])} {fmt(assumptions['junction_ponded_area_m2'])}")
    outfall = nodes[outfall_id]
    outfall_invert = float(outfall["ground_elevation_m"]) - invert_offset
    lines.extend(["", ";; Verified P4 outfall", "[OUTFALLS]", ";;Name Elevation Type Gated", f"{outfall_id} {fmt(outfall_invert)} {assumptions['outfall_type']} {assumptions['outfall_flap_gate']}", "", ";; Components without a verified outfall use closed terminal junctions; no SWMM outfall is fabricated.", "[CONDUITS]", ";;Name FromNode ToNode Length Roughness InOffset OutOffset InitFlow MaxFlow"])
    for link in model_links:
        lines.append(f"{link['link_id']} {link['from_node']} {link['to_node']} {fmt(link['length_m'])} {fmt(assumptions['conduit_roughness_manning_n'])} {fmt(assumptions['conduit_inlet_offset_m'])} {fmt(assumptions['conduit_outlet_offset_m'])} {fmt(assumptions['initial_link_flow_cms'])} 0")
    lines.extend(["", "[XSECTIONS]", ";;Link Shape Geom1 Geom2 Geom3 Geom4 Barrels"])
    for link in model_links:
        lines.append(f"{link['link_id']} {assumptions['conduit_shape']} {fmt(assumptions['conduit_diameter_m'])} 0 0 0 1")
    lines.extend(["", "[TIMESERIES]", ";;Name Date Time Value"])
    for record in storm["records"]:
        date, time = dt_parts(record["timestamp"])
        intensity = float(record["rainfall_mm"]) / (float(storm["timestep_seconds"]) / 3600.0)
        lines.append(f"SyntheticStorm {date} {time} {fmt(intensity)}")
    lines.extend(["", "[COORDINATES]", ";;Node X-Coord Y-Coord"])
    for node in sorted([nodes[node_id] for node_id in simulated_node_ids], key=lambda item: item["node_id"]):
        coordinates = node["coordinates"]
        lines.append(f"{node['node_id']} {fmt(coordinates[0])} {fmt(coordinates[1])}")
    lines.extend(["", "[REPORT]", "INPUT YES", "CONTROLS NO", "SUBCATCHMENTS ALL", "NODES ALL", "LINKS ALL", "", "[TAGS]", ";;ObjectType ObjectID Tag"])
    for item in simulated_assessments:
        lines.append(f"; component {item['component_id']} boundary={item['boundary_type']} nodes={','.join(item['boundary_node_ids'])}")
    for node in sorted([nodes[node_id] for node_id in simulated_node_ids], key=lambda item: item["node_id"]):
        lines.append(f"NODE {node['node_id']} p4_{component_by_node[node['node_id']]}")
    for link in model_links:
        lines.append(f"LINK {link['link_id']} p4_{component_by_node[link['from_node']]}")
    lines.append("")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text("\n".join(lines), encoding="utf-8")
    coverage["processing_date_utc"] = datetime.now(timezone.utc).isoformat()
    coverage["model_file"] = str(MODEL_PATH.relative_to(ROOT)).replace("\\", "/")
    storm_total_mm = sum(float(record["rainfall_mm"]) for record in storm["records"])
    previous_rainfall_validation = previous_coverage.get("rainfall_validation", {})
    previous_actual_volume = previous_rainfall_validation.get("actual_swmm_rainfall_volume_m3")
    try:
        actual_swmm_rainfall_volume = float(previous_actual_volume)
        if not math.isfinite(actual_swmm_rainfall_volume):
            actual_swmm_rainfall_volume = None
    except (TypeError, ValueError):
        actual_swmm_rainfall_volume = None
    rainfall_difference = (
        storm_total_mm / 1000.0 * float(coverage["modeled_subcatchment_area_m2"])
        - actual_swmm_rainfall_volume
        if actual_swmm_rainfall_volume is not None
        else None
    )
    coverage["rainfall_validation"] = {
        "source": storm["source"],
        "total_rainfall_mm": storm_total_mm,
        "expected_rainfall_volume_m3": storm_total_mm
        / 1000.0
        * float(coverage["modeled_subcatchment_area_m2"]),
        "actual_swmm_rainfall_volume_m3": actual_swmm_rainfall_volume,
        "difference_m3": rainfall_difference,
        "difference_is_report_rounding": abs(rainfall_difference) <= 100.0 if rainfall_difference is not None else None,
        "note": "The authoritative SWMM report value is written by scripts/data/run_swmm.py and preserved when the model is rebuilt.",
    }
    COVERAGE_PATH.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    SUBCATCHMENT_GEOJSON_PATH.write_text(json.dumps(subcatchment_geojson, indent=2) + "\n", encoding="utf-8")

    mapping_nodes = []
    excluded_nodes = []
    assessment_by_id = {item["component_id"]: item for item in assessments}
    for node_id in node_ids:
        node = nodes[node_id]
        component_id = component_by_node[node_id]
        assessment = assessment_by_id[component_id]
        if assessment["status"] == "simulated":
            mapping_nodes.append({"p4_id": node_id, "swmm_id": node_id, "source": node.get("source"), "component_id": component_id, "feature_type": "outfall" if node_id == outfall_id else "junction", "status": "mapped", "ground_elevation_m": node.get("ground_elevation_m"), "ground_elevation_source": "P4 DEM-sampled", "invert_elevation_m": float(node["ground_elevation_m"]) - invert_offset, "invert_elevation_source": "model_assumption", "invert_rule": "P4 ground_elevation_m minus configurable invert_offset_below_ground_m"})
        else:
            excluded_nodes.append({"p4_id": node_id, "swmm_id": None, "source": node.get("source"), "component_id": component_id, "feature_type": node.get("node_type"), "status": "excluded", "exclusion_reason": assessment["exclusion_reason"]})
    mapping_links = [{"p4_id": link["link_id"], "swmm_id": link["link_id"], "source": link.get("source"), "component_id": component_by_node[link["from_node"]], "feature_type": "conduit", "status": "mapped", "p4_from_node": link["from_node"], "p4_to_node": link["to_node"], "swmm_from_node": model_link_by_id[link["link_id"]]["from_node"], "swmm_to_node": model_link_by_id[link["link_id"]]["to_node"], "length_m": link.get("length_m"), "direction_source": link.get("direction_status")} for link in sorted(links, key=lambda item: item["link_id"])]
    mapping = {
        "processing_script": SCRIPT_VERSION,
        "processing_date_utc": datetime.now(timezone.utc).isoformat(),
        "p4_totals": {"nodes": len(node_ids), "links": len(links), "components": len(graph_components)},
        "swmm_totals": {"nodes": len(mapping_nodes), "links": len(mapping_links), "outfalls": 1, "closed_terminal_component_boundaries": sum(item["boundary_type"] == "closed_terminal_junction" for item in simulated_assessments)},
        "node_mapping": {"mapped": mapping_nodes, "excluded": excluded_nodes},
        "link_mapping": {"mapped": mapping_links, "excluded": []},
        "coverage": {"mapped_p4_nodes": len(mapping_nodes), "excluded_p4_nodes": len(excluded_nodes), "mapped_p4_links": len(mapping_links), "excluded_p4_links": 0, "all_p4_features_accounted_for": len(mapping_nodes) + len(excluded_nodes) == len(node_ids) and len(mapping_links) == len(links)},
        "no_artificial_links": True,
    }
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    MAPPING_PATH.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    assessment_payload = {
        "processing_script": SCRIPT_VERSION,
        "processing_date_utc": datetime.now(timezone.utc).isoformat(),
        "p4_totals": {"nodes": len(node_ids), "links": len(links), "components": len(graph_components)},
        "outfall_candidate": outfall_id,
        "simulated_component_ids": [item["component_id"] for item in simulated_assessments],
        "excluded_component_ids": [item["component_id"] for item in assessments if item["status"] == "excluded"],
        "simulated_node_ids": simulated_node_ids,
        "simulated_link_ids": simulated_link_ids,
        "simulated_totals": {"components": len(simulated_assessments), "nodes": len(simulated_node_ids), "links": len(simulated_link_ids)},
        "excluded_totals": {"components": len(assessments) - len(simulated_assessments), "nodes": len(excluded_nodes), "links": 0},
        "boundary_totals": {"verified_outfalls": 1, "closed_terminal_component_boundaries": sum(item["boundary_type"] == "closed_terminal_junction" for item in simulated_assessments), "closed_terminal_nodes": sum(len(item["boundary_node_ids"]) for item in simulated_assessments if item["boundary_type"] == "closed_terminal_junction")},
        "components": assessments,
        "direction_adjustments": direction_adjustments,
        "mapping": {"junction": "SWMM JUNCTIONS", "outfall_candidate": "SWMM OUTFALLS", "drainage_link": "SWMM CONDUITS + XSECTIONS", "closed_terminal_component": "SWMM junctions with no fabricated outfall; boundary is model_assumption", "terrain_inferred_inlet_candidates": "excluded until a verified association/coupling stage"},
        "exclusion_policy": "All valid P4 linked components are simulated. A P4 component is excluded only when it has no usable link or invalid geometry/topology; isolated terrain candidates are not converted into hydraulic infrastructure.",
        "model_file": str(MODEL_PATH.relative_to(ROOT)).replace("\\", "/"),
        "mapping_file": str(MAPPING_PATH.relative_to(ROOT)).replace("\\", "/"),
        "subcatchment_coverage_file": str(COVERAGE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "assumption_source": "model_assumption",
    }
    METADATA_PATH.write_text(json.dumps(assessment_payload, indent=2) + "\n", encoding="utf-8")
    return assessment_payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(build_model(), indent=2))


if __name__ == "__main__":
    main()
