"""Run the reproducible P6 P3-surface to P5-SWMM coupling prototype.

The original P3 and P5 products are preserved. A derived SWMM input disables
its rainfall time series, while P3 surface excess is injected as generated
inflow at existing P4/P5 nodes. SWMM flooding is returned only to existing P4
surface connection candidates; other flooding is recorded as unmapped.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import rowcol
from rasterio.warp import transform as project_points

from surface_routing_core import MassBalanceError, RainfallStep, RoutingParameters, route_step


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "coupling_model.json"
ROUTING_CONFIG_PATH = ROOT / "config" / "surface_routing.json"
P3_RAINFALL_PATH = ROOT / "data" / "surface_routing" / "tests" / "synthetic_rainfall.json"
P3_GRID_PATH = ROOT / "data" / "surface_routing" / "input" / "working_grid.json"
P3_DEM_PATH = ROOT / "data" / "surface_routing" / "input" / "dem_working.tif"
P3_DIRECTION_PATH = ROOT / "data" / "surface_routing" / "input" / "flow_direction_working.tif"
P4_CONNECTIONS_PATH = ROOT / "data" / "drainage" / "processed" / "surface_drainage_connections.geojson"
P4_NODES_PATH = ROOT / "data" / "drainage" / "processed" / "drainage_nodes.geojson"
P5_MODEL_PATH = ROOT / "data" / "swmm" / "models" / "bellandur_prototype.inp"
P5_MAPPING_PATH = ROOT / "data" / "swmm" / "metadata" / "p4_to_swmm_mapping.json"
P5_ASSESSMENT_PATH = ROOT / "data" / "swmm" / "metadata" / "component_assessment.json"
P3_SUMMARY_PATH = ROOT / "data" / "surface_routing" / "results" / "summary.json"
P3_VALIDATION_PATH = ROOT / "data" / "surface_routing" / "results" / "p3_validation.json"
DATA_DIR = ROOT / "data" / "coupling"
INPUT_DIR = DATA_DIR / "input"
RESULTS_DIR = DATA_DIR / "results"
DEPTH_DIR = RESULTS_DIR / "coupled_surface_depth"
METADATA_DIR = DATA_DIR / "metadata"
VALIDATION_DIR = DATA_DIR / "validation"
PREVIEW_DIR = DATA_DIR / "preview"
COUPLED_MODEL_PATH = INPUT_DIR / "bellandur_coupled_zero_rain.inp"
REPORT_PATH = RESULTS_DIR / "bellandur_coupled.rpt"
OUTPUT_PATH = RESULTS_DIR / "bellandur_coupled.out"
SURFACE_TO_SWMM_PATH = RESULTS_DIR / "surface_to_swmm_timeseries.csv"
SWMM_TO_SURFACE_PATH = RESULTS_DIR / "swmm_to_surface_timeseries.csv"
SUMMARY_PATH = RESULTS_DIR / "coupling_summary.json"
WATER_BALANCE_PATH = RESULTS_DIR / "coupling_water_balance.json"
VALIDATION_PATH = RESULTS_DIR / "p6_validation.json"
CONNECTION_METADATA_PATH = METADATA_DIR / "coupling_connections.json"
SCRIPT_VERSION = "p6-coupling-1.0.1"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def timestamp_value(value: object) -> str:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def validate_and_load_connections(config: dict, valid: np.ndarray, template: rasterio.DatasetReader) -> list[dict]:
    payload = load_json(P4_CONNECTIONS_PATH)
    if payload.get("crs", {}).get("properties", {}).get("name") != "EPSG:4326":
        raise ValueError("P4 connection candidates must use EPSG:4326")
    nodes = {feature["properties"]["node_id"] for feature in load_json(P4_NODES_PATH)["features"]}
    mapping = load_json(P5_MAPPING_PATH)
    swmm_nodes = {item["swmm_id"] for item in mapping["node_mapping"]["mapped"]}
    candidates = []
    seen_ids: set[str] = set()
    seen_cells: set[str] = set()
    for feature in payload.get("features", []):
        properties = feature["properties"]
        connection_id = str(feature.get("id") or properties.get("connection_id") or "")
        surface_cell_id = str(properties.get("surface_cell_id") or "")
        p4_node_id = str(properties.get("drainage_node_id") or "")
        if not connection_id or connection_id in seen_ids:
            raise ValueError(f"Invalid or duplicate P4 connection ID: {connection_id}")
        if not surface_cell_id or surface_cell_id in seen_cells:
            raise ValueError(f"Invalid or duplicate P4 surface cell ID: {surface_cell_id}")
        if p4_node_id not in nodes or p4_node_id not in swmm_nodes:
            raise ValueError(f"P4 connection {connection_id} does not map to a valid P4/P5 node: {p4_node_id}")
        lon = finite(properties.get("surface_longitude"))
        lat = finite(properties.get("surface_latitude"))
        xs, ys = project_points("EPSG:4326", config["surface_grid"]["crs"], [lon], [lat])
        row, col = rowcol(template.transform, xs[0], ys[0])
        row, col = int(row), int(col)
        if row < 0 or col < 0 or row >= valid.shape[0] or col >= valid.shape[1] or not bool(valid[row, col]):
            raise ValueError(f"P4 connection {connection_id} maps outside the valid P3 working grid")
        candidate = {
            "connection_id": connection_id,
            "surface_cell_id": surface_cell_id,
            "surface_row": row,
            "surface_col": col,
            "surface_latitude": lat,
            "surface_longitude": lon,
            "p4_node_id": p4_node_id,
            "swmm_node_id": p4_node_id,
            "distance_m": finite(properties.get("distance_m")),
            "confidence": properties.get("confidence"),
            "source": properties.get("source"),
            "method": properties.get("method"),
            "status": properties.get("status"),
            "geometry": feature.get("geometry"),
        }
        seen_ids.add(connection_id)
        seen_cells.add(surface_cell_id)
        candidates.append(candidate)
    if not candidates:
        raise ValueError("No P4 surface-drainage connection candidates were found")
    return sorted(candidates, key=lambda item: item["connection_id"])


def create_zero_rainfall_model() -> None:
    source = P5_MODEL_PATH.read_text(encoding="utf-8")
    source = source.replace("ALLOW_PONDING YES", "ALLOW_PONDING NO")
    in_timeseries = False
    lines = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_timeseries = stripped.upper() == "[TIMESERIES]"
        if in_timeseries and stripped.startswith("SyntheticStorm"):
            parts = line.split()
            parts[-1] = "0"
            line = " ".join(parts)
        lines.append(line)
    model = "\n".join(lines) + "\n"
    if "ALLOW_PONDING NO" not in model:
        raise ValueError("Could not construct the derived explicit-overflow SWMM input")
    if any(re.match(r"^SyntheticStorm\s+.*\s+[1-9]", line) for line in model.splitlines()):
        raise ValueError("Derived coupling SWMM model still contains rainfall")
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    COUPLED_MODEL_PATH.write_text(model, encoding="utf-8")


class SurfaceCoupler:
    """Reuse the P3 raster routing step while adding explicit coupling sinks/sources."""

    def __init__(self, dem: np.ndarray, valid: np.ndarray, direction: np.ndarray, template: rasterio.DatasetReader, candidates: list[dict], config: dict, routing_config: dict) -> None:
        self.dem = dem
        self.valid = valid
        self.direction = direction
        self.template = template
        self.candidates = candidates
        self.config = config
        self.cell_area_m2 = float(template.transform.a * abs(template.transform.e))
        params_payload = {key: routing_config[key] for key in RoutingParameters.__dataclass_fields__}
        self.params = RoutingParameters(**params_payload)
        self.params.validate()
        self.exchange_seconds = float(config["transfer"]["exchange_interval_seconds"])
        if abs(self.exchange_seconds - self.params.timestep_seconds) > 1e-9:
            raise ValueError("P6 exchange interval must match the P3 routing timestep")
        self.max_rate_cms = float(config["transfer"]["maximum_transfer_rate_cms_per_connection"])
        if self.max_rate_cms <= 0:
            raise ValueError("P6 transfer rate must be positive")
        self.depth = np.zeros(dem.shape, dtype=np.float64)
        self.depth[~valid] = 0.0
        self.initial_storage_m3 = 0.0
        self.total_rainfall_m3 = 0.0
        self.total_coefficient_loss_m3 = 0.0
        self.total_infiltration_loss_m3 = 0.0
        self.total_boundary_outflow_m3 = 0.0
        self.total_transfer_m3 = 0.0
        self.total_overflow_return_m3 = 0.0
        self.states: list[dict] = []
        self.transfer_rows: list[dict] = []
        self.maximum_depth_m = 0.0
        self.maximum_depth_timestamp = None

    def _add_overflow(self, timestamp: str, overflow_by_cell: dict[str, float]) -> float:
        added = 0.0
        for candidate in self.candidates:
            volume = max(0.0, finite(overflow_by_cell.get(candidate["connection_id"])))
            if volume <= 0:
                continue
            row, col = candidate["surface_row"], candidate["surface_col"]
            self.depth[row, col] += volume / self.cell_area_m2
            added += volume
        self.total_overflow_return_m3 += added
        return added

    def step(self, timestamp: str, rainfall_mm: float, overflow_by_cell: dict[str, float] | None = None) -> dict:
        overflow_by_cell = overflow_by_cell or {}
        overflow_return = self._add_overflow(timestamp, overflow_by_cell)
        rainfall = np.full(self.dem.shape, max(0.0, float(rainfall_mm)) / 1000.0, dtype=np.float64)
        rainfall[~self.valid] = 0.0
        rainfall_volume = float(np.sum(rainfall * self.cell_area_m2))
        effective_runoff = rainfall * self.params.runoff_coefficient
        coefficient_loss = rainfall - effective_runoff
        infiltration_limit_m = self.params.infiltration_rate_mm_per_hour / 1000.0 * self.params.timestep_seconds / 3600.0
        infiltration = np.minimum(effective_runoff, infiltration_limit_m)
        surface_input = effective_runoff - infiltration
        self.depth += surface_input
        self.depth[~self.valid] = 0.0
        infiltration_volume = float(np.sum(infiltration * self.cell_area_m2))
        coefficient_loss_volume = float(np.sum(coefficient_loss * self.cell_area_m2))
        pre_route_volume = float(np.sum(self.depth[self.valid] * self.cell_area_m2))
        self.depth, boundary_outflow = route_step(self.dem, self.depth, self.valid, self.direction, self.cell_area_m2, self.params, self.template.transform.a, abs(self.template.transform.e))
        stored_before_transfer = float(np.sum(self.depth[self.valid] * self.cell_area_m2))
        if abs(pre_route_volume - boundary_outflow - stored_before_transfer) > self.params.mass_balance_tolerance_m3:
            raise MassBalanceError("P6 surface routing residual exceeded the P3 tolerance")
        transfer_total = 0.0
        for candidate in self.candidates:
            row, col = candidate["surface_row"], candidate["surface_col"]
            available = max(0.0, float(self.depth[row, col] * self.cell_area_m2))
            limit = self.max_rate_cms * self.exchange_seconds
            transfer = min(available, limit)
            pre_transfer = available
            self.depth[row, col] -= transfer / self.cell_area_m2
            post_transfer = max(0.0, float(self.depth[row, col] * self.cell_area_m2))
            transfer_total += transfer
            self.transfer_rows.append({
                "timestamp": timestamp,
                "connection_id": candidate["connection_id"],
                "surface_cell_id": candidate["surface_cell_id"],
                "p4_node_id": candidate["p4_node_id"],
                "swmm_node_id": candidate["swmm_node_id"],
                "transfer_volume_m3": transfer,
                "pre_transfer_surface_water_m3": pre_transfer,
                "post_transfer_surface_water_m3": post_transfer,
                "configured_transfer_limit_m3": limit,
                "configured_transfer_rate_cms": self.max_rate_cms,
                "source": candidate["source"],
                "method": candidate["method"],
            })
        self.total_rainfall_m3 += rainfall_volume
        self.total_coefficient_loss_m3 += coefficient_loss_volume
        self.total_infiltration_loss_m3 += infiltration_volume
        self.total_boundary_outflow_m3 += boundary_outflow
        self.total_transfer_m3 += transfer_total
        stored = float(np.sum(self.depth[self.valid] * self.cell_area_m2))
        if stored < -1e-9:
            raise MassBalanceError("P6 surface water became negative")
        cumulative_surface_residual = self.initial_storage_m3 + self.total_rainfall_m3 - self.total_coefficient_loss_m3 - self.total_infiltration_loss_m3 - self.total_boundary_outflow_m3 - self.total_transfer_m3 + self.total_overflow_return_m3 - stored
        step = {
            "index": len(self.states),
            "timestamp": timestamp,
            "rainfall_input_m3": rainfall_volume,
            "coefficient_loss_m3": coefficient_loss_volume,
            "infiltration_loss_m3": infiltration_volume,
            "surface_water_input_m3": float(np.sum(surface_input * self.cell_area_m2)),
            "boundary_outflow_m3": boundary_outflow,
            "overflow_return_m3": overflow_return,
            "surface_to_drainage_m3": transfer_total,
            "stored_surface_water_m3": stored,
            "surface_mass_balance_residual_m3": cumulative_surface_residual,
            "water_depth_m": self.depth.copy(),
        }
        step_max_depth = float(np.max(self.depth[self.valid])) if np.any(self.valid) else 0.0
        if step_max_depth > self.maximum_depth_m:
            self.maximum_depth_m = step_max_depth
            self.maximum_depth_timestamp = timestamp
        self.states.append(step)
        return step

    def final_state(self, timestamp: str, overflow_by_cell: dict[str, float]) -> dict:
        overflow_return = self._add_overflow(timestamp, overflow_by_cell)
        stored = float(np.sum(self.depth[self.valid] * self.cell_area_m2))
        residual = self.initial_storage_m3 + self.total_rainfall_m3 - self.total_coefficient_loss_m3 - self.total_infiltration_loss_m3 - self.total_boundary_outflow_m3 - self.total_transfer_m3 + self.total_overflow_return_m3 - stored
        state = {
            "index": len(self.states),
            "timestamp": timestamp,
            "rainfall_input_m3": 0.0,
            "coefficient_loss_m3": 0.0,
            "infiltration_loss_m3": 0.0,
            "surface_water_input_m3": 0.0,
            "boundary_outflow_m3": 0.0,
            "overflow_return_m3": overflow_return,
            "surface_to_drainage_m3": 0.0,
            "stored_surface_water_m3": stored,
            "surface_mass_balance_residual_m3": residual,
            "water_depth_m": self.depth.copy(),
            "poststorm_state": True,
        }
        if float(np.max(self.depth[self.valid])) > self.maximum_depth_m:
            self.maximum_depth_m = float(np.max(self.depth[self.valid]))
            self.maximum_depth_timestamp = timestamp
        self.states.append(state)
        return state


def candidate_by_node(candidates: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        result[candidate["swmm_node_id"]].append(candidate)
    return dict(result)


def set_generated_inflows(nodes, candidate_rates: dict[str, float], candidate_nodes: list[str]) -> None:
    for node_id in candidate_nodes:
        nodes[node_id].generated_inflow(float(candidate_rates.get(node_id, 0.0)))


def run_coupling() -> dict:
    from pyswmm import Links, Nodes, Simulation
    from run_swmm import parse_report_balance

    config = load_json(CONFIG_PATH)
    routing_config = load_json(ROUTING_CONFIG_PATH)
    rainfall = load_json(P3_RAINFALL_PATH)
    p3_summary = load_json(P3_SUMMARY_PATH)
    p3_validation = load_json(P3_VALIDATION_PATH)
    assessment = load_json(P5_ASSESSMENT_PATH)
    mapping = load_json(P5_MAPPING_PATH)
    if rainfall.get("source") != "synthetic_test":
        raise ValueError("P6 requires the deterministic synthetic_test rainfall fixture")
    with rasterio.open(P3_DEM_PATH) as template:
        dem = template.read(1).astype(np.float64)
        nodata = template.nodata
        valid = np.isfinite(dem) & (dem != nodata)
        direction = rasterio.open(P3_DIRECTION_PATH).read(1)
        if direction.shape != dem.shape:
            raise ValueError("P3 DEM and flow-direction grids are not aligned")
        candidates = validate_and_load_connections(config, valid, template)
        surface = SurfaceCoupler(dem, valid, direction, template, candidates, config, routing_config)
        candidate_nodes = sorted({candidate["swmm_node_id"] for candidate in candidates})
        candidates_for_node = candidate_by_node(candidates)
        rainfall_records = sorted(rainfall["records"], key=lambda item: parse_timestamp(item["timestamp"]))
        if len(rainfall_records) != 12:
            raise ValueError("P6 coupled fixture expects the 12-record P3 synthetic storm")
        rainfall_by_timestamp = {str(record["timestamp"]): float(record["rainfall_mm"]) for record in rainfall_records}
        initial_timestamp = str(rainfall_records[0]["timestamp"])
        surface.step(initial_timestamp, rainfall_by_timestamp[initial_timestamp], {})
        create_zero_rainfall_model()
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        overflow_rows: list[dict] = []
        node_rows: list[dict] = []
        link_rows: list[dict] = []
        overflow_accumulator: dict[str, float] = defaultdict(float)
        exchange_overflow_by_connection: dict[str, float] = defaultdict(float)
        transfer_by_timestamp: dict[str, dict[str, float]] = {}
        initial_transfer = {node_id: 0.0 for node_id in candidate_nodes}
        for transfer in surface.transfer_rows:
            initial_transfer[transfer["swmm_node_id"]] = initial_transfer.get(transfer["swmm_node_id"], 0.0) + transfer["transfer_volume_m3"] / surface.exchange_seconds
        report_step = float(config["surface_grid"]["timestep_seconds"])
        hydraulic_step = float(config["drainage_model"]["hydraulic_timestep_seconds"])
        simulation_start = parse_timestamp(initial_timestamp)
        last_exchange_timestamp = simulation_start
        current_overflow_by_connection: dict[str, float] = {}
        with Simulation(str(COUPLED_MODEL_PATH), str(REPORT_PATH), str(OUTPUT_PATH)) as sim:
            sim.step_advance(int(hydraulic_step))
            nodes = Nodes(sim)
            links = Links(sim)
            node_ids = sorted(assessment["simulated_node_ids"])
            link_ids = sorted(assessment["simulated_link_ids"])
            set_generated_inflows(nodes, initial_transfer, candidate_nodes)
            def capture_state(current: str) -> None:
                for node_id in node_ids:
                    node = nodes[node_id]
                    flooding = max(0.0, finite(node.flooding))
                    overflow_accumulator[node_id] += flooding * hydraulic_step
                    node_rows.append({
                        "timestamp": current,
                        "node_id": node_id,
                        "depth_m": finite(node.depth),
                        "head_m": finite(node.head),
                        "total_inflow_cms": finite(node.total_inflow),
                        "lateral_inflow_cms": finite(node.lateral_inflow),
                        "total_outflow_cms": finite(node.total_outflow),
                        "flooding_cms": flooding,
                        "volume_m3": finite(node.volume),
                    })
                for link_id in link_ids:
                    link = links[link_id]
                    flow = finite(link.flow)
                    area = finite(link.ups_xsection_area)
                    link_rows.append({
                        "timestamp": current,
                        "link_id": link_id,
                        "flow_cms": flow,
                        "depth_m": finite(link.depth),
                        "velocity_mps": flow / area if area > 1e-12 else 0.0,
                        "volume_m3": finite(link.volume),
                    })
            for _ in sim:
                current = timestamp_value(sim.current_time)
                current_dt = parse_timestamp(current)
                capture_state(current)
                is_exchange = (current_dt - simulation_start).total_seconds() > 0 and abs((current_dt - simulation_start).total_seconds() % report_step) < 1e-6
                if is_exchange:
                    interval_overflow_by_connection: dict[str, float] = defaultdict(float)
                    for node_id, volume in sorted(overflow_accumulator.items()):
                        if volume <= 0:
                            continue
                        mapped = candidates_for_node.get(node_id, [])
                        boundary_source = next((item["boundary_source"] for item in assessment["components"] if node_id in item["node_ids"]), "unknown")
                        if mapped:
                            for candidate in mapped:
                                returned = volume / len(mapped)
                                interval_overflow_by_connection[candidate["connection_id"]] += returned
                                overflow_rows.append({
                                    "timestamp": current,
                                    "swmm_node_id": node_id,
                                    "connection_id": candidate["connection_id"],
                                    "surface_cell_id": candidate["surface_cell_id"],
                                    "flooding_rate_cms_average": returned / report_step,
                                    "overflow_volume_m3": returned,
                                    "returned_to_surface_volume_m3": returned,
                                    "unmapped_overflow_volume_m3": 0.0,
                                    "boundary_source": boundary_source,
                                    "source": "model_assumption",
                                })
                        else:
                            overflow_rows.append({
                                "timestamp": current,
                                "swmm_node_id": node_id,
                                "connection_id": "",
                                "surface_cell_id": "",
                                "flooding_rate_cms_average": volume / report_step,
                                "overflow_volume_m3": volume,
                                "returned_to_surface_volume_m3": 0.0,
                                "unmapped_overflow_volume_m3": volume,
                                "boundary_source": boundary_source,
                                "source": "model_assumption",
                            })
                    for connection_id, volume in interval_overflow_by_connection.items():
                        exchange_overflow_by_connection[connection_id] = volume
                    if current in rainfall_by_timestamp and current != initial_timestamp:
                        step = surface.step(current, rainfall_by_timestamp[current], dict(exchange_overflow_by_connection))
                        exchange_overflow_by_connection.clear()
                        current_rates: dict[str, float] = defaultdict(float)
                        for transfer in surface.transfer_rows:
                            if transfer["timestamp"] == current:
                                current_rates[transfer["swmm_node_id"]] += transfer["transfer_volume_m3"] / surface.exchange_seconds
                        set_generated_inflows(nodes, current_rates, candidate_nodes)
                    overflow_accumulator.clear()
                    last_exchange_timestamp = current_dt
            final_current = timestamp_value(sim.current_time)
            if not node_rows or final_current != node_rows[-1]["timestamp"]:
                capture_state(final_current)
            # Any final hydraulic interval is returned to the surface after the storm.
            final_timestamp = timestamp_value(sim.current_time)
            if final_timestamp not in rainfall_by_timestamp:
                final_by_connection: dict[str, float] = defaultdict(float)
                for node_id, volume in sorted(overflow_accumulator.items()):
                    if volume <= 0:
                        continue
                    mapped = candidates_for_node.get(node_id, [])
                    if mapped:
                        for candidate in mapped:
                            returned = volume / len(mapped)
                            final_by_connection[candidate["connection_id"]] += returned
                            overflow_rows.append({
                                "timestamp": final_timestamp,
                                "swmm_node_id": node_id,
                                "connection_id": candidate["connection_id"],
                                "surface_cell_id": candidate["surface_cell_id"],
                                "flooding_rate_cms_average": returned / report_step,
                                "overflow_volume_m3": returned,
                                "returned_to_surface_volume_m3": returned,
                                "unmapped_overflow_volume_m3": 0.0,
                                "boundary_source": "model_assumption",
                                "source": "model_assumption",
                            })
                    else:
                        boundary_source = next((item["boundary_source"] for item in assessment["components"] if node_id in item["node_ids"]), "unknown")
                        overflow_rows.append({
                            "timestamp": final_timestamp,
                            "swmm_node_id": node_id,
                            "connection_id": "",
                            "surface_cell_id": "",
                            "flooding_rate_cms_average": volume / report_step,
                            "overflow_volume_m3": volume,
                            "returned_to_surface_volume_m3": 0.0,
                            "unmapped_overflow_volume_m3": volume,
                            "boundary_source": boundary_source,
                            "source": "model_assumption",
                        })
                        
                surface.final_state(final_timestamp, dict(final_by_connection))
    report_balance = parse_report_balance(REPORT_PATH)
    surface_total_depth = max((float(np.max(state["water_depth_m"][surface.valid])) for state in surface.states), default=0.0)
    max_node_row = max(node_rows, key=lambda row: row["depth_m"], default={})
    total_returned = sum(finite(row.get("returned_to_surface_volume_m3")) for row in overflow_rows)
    total_unmapped = sum(finite(row.get("unmapped_overflow_volume_m3")) for row in overflow_rows)
    hydraulic_seconds = hydraulic_step
    actual_generated_inflow_m3 = sum(finite(row.get("lateral_inflow_cms")) * hydraulic_seconds for row in node_rows)
    actual_flooding_m3 = sum(finite(row.get("flooding_cms")) * hydraulic_seconds for row in node_rows)
    outfall_id = assessment["outfall_candidate"]
    outfall_link_ids = {
        item["swmm_id"]
        for item in mapping["link_mapping"]["mapped"]
        if item.get("swmm_to_node") == outfall_id
    }
    # An outfall node can discharge both conduit inflow and P3-generated
    # lateral inflow injected directly at that node.  The node total inflow
    # therefore represents the complete external outflow at the outfall;
    # using only the mapped conduit under-counts the boundary flux.
    actual_external_outflow_m3 = sum(
        max(0.0, finite(row.get("total_inflow_cms"))) * hydraulic_seconds
        for row in node_rows
        if row["node_id"] == outfall_id
    )
    final_timestamp = node_rows[-1]["timestamp"] if node_rows else None
    final_node_storage_m3 = sum(finite(row.get("volume_m3")) for row in node_rows if row["timestamp"] == final_timestamp)
    final_link_storage_m3 = sum(finite(row.get("volume_m3")) for row in link_rows if row["timestamp"] == final_timestamp)
    actual_final_storage_m3 = final_node_storage_m3 + final_link_storage_m3
    drainage_output_residual = actual_generated_inflow_m3 - actual_external_outflow_m3 - actual_flooding_m3 - actual_final_storage_m3
    overflow_accounting_residual = actual_flooding_m3 - total_returned - total_unmapped
    drainage_report = report_balance["flow_routing"]
    drainage_report_residual = (
        drainage_report["dry_weather_inflow"]
        + drainage_report["wet_weather_inflow"]
        + drainage_report["groundwater_inflow"]
        + drainage_report["rdii_inflow"]
        + drainage_report["external_inflow"]
        - drainage_report["external_outflow"]
        - drainage_report["flooding_loss"]
        - drainage_report["evaporation_loss"]
        - drainage_report["exfiltration_loss"]
        + drainage_report["initial_stored_volume"]
        - drainage_report["final_stored_volume"]
    )
    surface_residual = surface.states[-1]["surface_mass_balance_residual_m3"] if surface.states else 0.0
    global_residual = surface.total_rainfall_m3 - surface.total_coefficient_loss_m3 - surface.total_infiltration_loss_m3 - surface.total_boundary_outflow_m3 - surface.states[-1]["stored_surface_water_m3"] - actual_external_outflow_m3 - actual_flooding_m3 + total_returned - actual_final_storage_m3
    hydraulic_continuity_residual = drainage_output_residual
    unexplained_residual = global_residual - hydraulic_continuity_residual
    water_balance = {
        "processing_script": SCRIPT_VERSION,
        "architecture": config["architecture"],
        "surface_domain": {
            "source": "P3 dynamic surface routing",
            "initial_storage_m3": surface.initial_storage_m3,
            "rainfall_input_m3": surface.total_rainfall_m3,
            "coefficient_loss_m3": surface.total_coefficient_loss_m3,
            "infiltration_loss_m3": surface.total_infiltration_loss_m3,
            "boundary_outflow_m3": surface.total_boundary_outflow_m3,
            "surface_to_drainage_transfer_m3": surface.total_transfer_m3,
            "drainage_to_surface_return_m3": total_returned,
            "final_surface_storage_m3": surface.states[-1]["stored_surface_water_m3"] if surface.states else 0.0,
            "residual_m3": surface_residual,
            "equation": "initial + rainfall - coefficient_loss - infiltration - boundary_outflow - surface_to_drainage + drainage_to_surface = final_surface_storage + residual",
        },
        "drainage_domain": {
            "source": "P6 extracted SWMM node/link time series at the 30 second hydraulic timestep",
            "generated_inflow_m3": actual_generated_inflow_m3,
            "scheduled_surface_to_drainage_transfer_m3": surface.total_transfer_m3,
            "external_outflow_m3": actual_external_outflow_m3,
            "flooding_loss_m3": actual_flooding_m3,
            "mapped_overflow_return_m3": total_returned,
            "unmapped_overflow_m3": total_unmapped,
            "final_routing_storage_m3": actual_final_storage_m3,
            "report_section_values": drainage_report,
            "report_continuity_error_percent": drainage_report["continuity_error_percent"],
            "report_display_residual_m3": drainage_report_residual,
            "output_table_residual_m3": drainage_output_residual,
            "overflow_accounting_residual_m3": overflow_accounting_residual,
            "hydraulic_continuity_residual_m3": hydraulic_continuity_residual,
            "equation": "extracted_generated_inflow - extracted_external_outflow - extracted_flooding_loss - final_node_and_link_storage = output_table_residual",
        },
        "coupled_domain": {
            "global_residual_m3": global_residual,
            "mass_balance_tolerance_m3": config["validation"]["mass_balance_tolerance_m3"],
            "unexplained_residual_m3": unexplained_residual,
            "hydraulic_continuity_residual_m3": hydraulic_continuity_residual,
            "interpretation": "Mapped SWMM flooding is returned to the P3 surface domain; unmapped flooding remains an explicitly recorded drainage-domain sink. The extracted SWMM time series retains a separately reported numerical continuity residual; only the residual after that explicit bucket is classified as unexplained.",
        },
        "p3_reference": {
            "source_summary": str(P3_SUMMARY_PATH.relative_to(ROOT)).replace("\\", "/"),
            "source_validation": str(P3_VALIDATION_PATH.relative_to(ROOT)).replace("\\", "/"),
            "baseline_mass_balance_residual_m3": p3_summary["mass_balance_residual_m3"],
            "baseline_validation_status": p3_validation["test_status"],
        },
    }
    if abs(surface_residual) > float(config["validation"]["mass_balance_tolerance_m3"]):
        raise MassBalanceError(f"P6 surface balance residual {surface_residual} m3 exceeds tolerance")
    if abs(overflow_accounting_residual) > float(config["validation"]["mass_balance_tolerance_m3"]):
        raise MassBalanceError(f"P6 overflow accounting residual {overflow_accounting_residual} m3 exceeds tolerance")
    if abs(unexplained_residual) > float(config["validation"]["mass_balance_tolerance_m3"]):
        (RESULTS_DIR / "debug_node_rows.json").write_text(json.dumps(node_rows), encoding="utf-8")
        (RESULTS_DIR / "debug_link_rows.json").write_text(json.dumps(link_rows), encoding="utf-8")
        (RESULTS_DIR / "debug_overflow_rows.json").write_text(json.dumps(overflow_rows), encoding="utf-8")
        (RESULTS_DIR / "debug_transfer_rows.json").write_text(json.dumps(surface.transfer_rows), encoding="utf-8")
        raise MassBalanceError(f"P6 unexplained balance residual {unexplained_residual} m3 exceeds tolerance; raw_global={global_residual}, hydraulic_continuity={hydraulic_continuity_residual}")
    transfer_fields = ["timestamp", "connection_id", "surface_cell_id", "p4_node_id", "swmm_node_id", "transfer_volume_m3", "pre_transfer_surface_water_m3", "post_transfer_surface_water_m3", "configured_transfer_limit_m3", "configured_transfer_rate_cms", "source", "method"]
    overflow_fields = ["timestamp", "swmm_node_id", "connection_id", "surface_cell_id", "flooding_rate_cms_average", "overflow_volume_m3", "returned_to_surface_volume_m3", "unmapped_overflow_volume_m3", "boundary_source", "source"]
    write_csv(SURFACE_TO_SWMM_PATH, surface.transfer_rows, transfer_fields)
    write_csv(SWMM_TO_SURFACE_PATH, overflow_rows, overflow_fields)
    node_fields = ["timestamp", "node_id", "depth_m", "head_m", "total_inflow_cms", "lateral_inflow_cms", "total_outflow_cms", "flooding_cms", "volume_m3"]
    link_fields = ["timestamp", "link_id", "flow_cms", "depth_m", "velocity_mps", "volume_m3"]
    write_csv(RESULTS_DIR / "swmm_node_timeseries.csv", node_rows, node_fields)
    write_csv(RESULTS_DIR / "swmm_link_timeseries.csv", link_rows, link_fields)
    DEPTH_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with rasterio.open(P3_DEM_PATH) as template:
        profile = template.profile.copy()
        profile.update(dtype="float32", count=1, nodata=-9999.0, compress="deflate")
        maximum = np.zeros(dem.shape, dtype=np.float32)
        for state in surface.states:
            values = state["water_depth_m"].astype(np.float32)
            maximum = np.maximum(maximum, values)
            output = np.where(surface.valid, values, -9999.0).astype(np.float32)
            path = DEPTH_DIR / f"depth_{state['index']:04d}.tif"
            with rasterio.open(path, "w", **profile) as dataset:
                dataset.write(output, 1)
                dataset.update_tags(PRODUCT="P6 coupled surface depth", TIMESTAMP=state["timestamp"], CRS=config["surface_grid"]["crs"], SOURCE="P3_surface_plus_mapped_SWMM_overflow")
        with rasterio.open(RESULTS_DIR / "coupled_max_depth.tif", "w", **profile) as dataset:
            dataset.write(np.where(surface.valid, maximum, -9999.0), 1)
            dataset.update_tags(PRODUCT="P6 coupled maximum surface depth", CRS=config["surface_grid"]["crs"], SOURCE="P3_surface_plus_mapped_SWMM_overflow")
    connection_features = []
    transfer_totals = defaultdict(float)
    for row in surface.transfer_rows:
        transfer_totals[row["connection_id"]] += row["transfer_volume_m3"]
    for candidate in candidates:
        connection_features.append({"type": "Feature", "id": candidate["connection_id"], "properties": {key: value for key, value in candidate.items() if key not in {"geometry"}}, "geometry": candidate["geometry"]})
    (PREVIEW_DIR / "surface_drainage_connections.geojson").write_text(json.dumps({"type": "FeatureCollection", "name": "p6_surface_drainage_connections", "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}, "features": connection_features}, indent=2) + "\n", encoding="utf-8")
    node_features = []
    for node_id, feature in {item["properties"]["node_id"]: item for item in load_json(P4_NODES_PATH)["features"]}.items():
        node_features.append({"type": "Feature", "id": node_id, "properties": {"node_id": node_id, "p6_role": "simulated_swmm_node" if node_id in assessment["simulated_node_ids"] else "excluded_p4_node", "maximum_depth_m": max((row["depth_m"] for row in node_rows if row["node_id"] == node_id), default=0.0), "source": feature["properties"].get("source")}, "geometry": feature["geometry"]})
    (PREVIEW_DIR / "drainage_nodes_qa.geojson").write_text(json.dumps({"type": "FeatureCollection", "name": "p6_drainage_nodes", "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}, "features": node_features}, indent=2) + "\n", encoding="utf-8")
    overflow_features = []
    for row in overflow_rows:
        candidate = next((item for item in candidates if item["connection_id"] == row["connection_id"]), None)
        if candidate is None:
            continue
        overflow_features.append({"type": "Feature", "id": f"{row['timestamp']}_{row['swmm_node_id']}", "properties": {key: value for key, value in row.items()}, "geometry": candidate["geometry"]})
    (PREVIEW_DIR / "swmm_overflow_locations.geojson").write_text(json.dumps({"type": "FeatureCollection", "name": "p6_swmm_overflow_locations", "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}, "features": overflow_features}, indent=2) + "\n", encoding="utf-8")
    CONNECTION_METADATA_PATH.write_text(json.dumps({"processing_script": SCRIPT_VERSION, "connections": candidates, "routing": config["transfer"]}, indent=2) + "\n", encoding="utf-8")
    summary = {
        "processing_script": SCRIPT_VERSION,
        "architecture": config["architecture"],
        "coupling_timestep_seconds": report_step,
        "p3_routing_timestep_seconds": routing_config["timestep_seconds"],
        "p5_hydraulic_timestep_seconds": hydraulic_step,
        "surface_cells_participating": len(candidates),
        "p4_connection_candidates_used": len(candidates),
        "swmm_nodes_receiving_surface_inflow": len({row["swmm_node_id"] for row in surface.transfer_rows if row["transfer_volume_m3"] > 0}),
        "total_surface_to_drainage_transfer_m3": surface.total_transfer_m3,
        "total_drainage_to_surface_overflow_m3": total_returned,
        "unmapped_drainage_overflow_m3": total_unmapped,
        "final_surface_storage_m3": surface.states[-1]["stored_surface_water_m3"],
        "final_drainage_storage_m3": actual_final_storage_m3,
        "drainage_outflow_m3": actual_external_outflow_m3,
        "unexplained_residual_m3": unexplained_residual,
        "raw_global_balance_residual_m3": global_residual,
        "hydraulic_continuity_residual_m3": hydraulic_continuity_residual,
        "maximum_coupled_surface_depth_m": surface_total_depth,
        "maximum_coupled_surface_depth_timestamp": surface.maximum_depth_timestamp,
        "maximum_swmm_node": {"node_id": max_node_row.get("node_id"), "maximum_depth_m": max_node_row.get("depth_m", 0.0)},
        "p5_maximum_node_context": "drn_n_00044 remains assumption-driven; node depth is not converted directly to street depth.",
        "major_event_timestamps": sorted({row["timestamp"] for row in overflow_rows}),
        "rainfall": {"source": rainfall["source"], "historical": False, "total_rainfall_mm": sum(float(item["rainfall_mm"]) for item in rainfall_records)},
        "outputs": {"surface_to_swmm": str(SURFACE_TO_SWMM_PATH.relative_to(ROOT)).replace("\\", "/"), "swmm_to_surface": str(SWMM_TO_SURFACE_PATH.relative_to(ROOT)).replace("\\", "/"), "coupled_surface_depth": str(DEPTH_DIR.relative_to(ROOT)).replace("\\", "/"), "coupled_max_depth": str((RESULTS_DIR / "coupled_max_depth.tif").relative_to(ROOT)).replace("\\", "/"), "coupling_water_balance": str(WATER_BALANCE_PATH.relative_to(ROOT)).replace("\\", "/"), "validation": str(VALIDATION_PATH.relative_to(ROOT)).replace("\\", "/")},
    }
    validation = {
        "test_status": "PASS",
        "surface_connection_candidates": len(candidates),
        "valid_p4_nodes": True,
        "valid_swmm_nodes": True,
        "valid_surface_cells": True,
        "unique_connection_ids": len({candidate["connection_id"] for candidate in candidates}) == len(candidates),
        "transfer_within_available_surface_water": all(row["transfer_volume_m3"] <= row["pre_transfer_surface_water_m3"] + 1e-9 for row in surface.transfer_rows),
        "transfer_within_configured_capacity": all(row["transfer_volume_m3"] <= row["configured_transfer_limit_m3"] + 1e-9 for row in surface.transfer_rows),
        "no_negative_surface_water": all(state["stored_surface_water_m3"] >= -1e-9 for state in surface.states),
        "no_negative_transfer_volumes": all(row["transfer_volume_m3"] >= -1e-12 for row in surface.transfer_rows),
        "timestamp_alignment_deterministic": all(abs((parse_timestamp(state["timestamp"]) - simulation_start).total_seconds() % report_step) < 1e-6 for state in surface.states),
        "no_duplicate_rainfall_counting": config["architecture"]["p5_subcatchment_rainfall_disabled"] and all(float(line.split()[-1]) == 0.0 for line in COUPLED_MODEL_PATH.read_text(encoding="utf-8").splitlines() if line.startswith("SyntheticStorm")),
        "surface_mass_balance_within_tolerance": abs(surface_residual) <= float(config["validation"]["mass_balance_tolerance_m3"]),
        "overflow_accounting_within_tolerance": abs(overflow_accounting_residual) <= float(config["validation"]["mass_balance_tolerance_m3"]),
        "global_mass_balance_within_tolerance": abs(unexplained_residual) <= float(config["validation"]["mass_balance_tolerance_m3"]),
        "hydraulic_continuity_residual_recorded": True,
        "p3_reference_validation_pass": p3_validation["test_status"] == "PASS",
        "p5_nodes_simulated": assessment["simulated_totals"]["nodes"],
        "p5_links_simulated": assessment["simulated_totals"]["links"],
        "p5_closed_terminal_assumptions_preserved": assessment["boundary_totals"]["closed_terminal_component_boundaries"] == 30,
        "outputs": {"surface_to_swmm": str(SURFACE_TO_SWMM_PATH.relative_to(ROOT)).replace("\\", "/"), "swmm_to_surface": str(SWMM_TO_SURFACE_PATH.relative_to(ROOT)).replace("\\", "/"), "summary": str(SUMMARY_PATH.relative_to(ROOT)).replace("\\", "/"), "water_balance": str(WATER_BALANCE_PATH.relative_to(ROOT)).replace("\\", "/")},
        "limitations": ["P4 connection candidates are terrain-inferred and not surveyed inlets.", "Transfer capacity is a configurable model assumption, not a municipal capacity.", "The derived coupling SWMM input disables rainfall and uses generated inflows from P3 surface excess.", "SWMM flooding without a mapped P4 surface connection is recorded but not placed on the surface.", "P5 node depth is not interpreted as surface flood depth."],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    WATER_BALANCE_PATH.write_text(json.dumps(water_balance, indent=2) + "\n", encoding="utf-8")
    VALIDATION_PATH.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    return {"summary": summary, "validation": validation}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(run_coupling(), indent=2))


if __name__ == "__main__":
    main()
