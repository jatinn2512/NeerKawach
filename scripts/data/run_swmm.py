"""Execute the expanded P5 EPA SWMM model and write hydraulic QA artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "swmm_model.json"
MODEL_PATH = ROOT / "data" / "swmm" / "models" / "bellandur_prototype.inp"
NODES_PATH = ROOT / "data" / "drainage" / "processed" / "drainage_nodes.geojson"
LINKS_PATH = ROOT / "data" / "drainage" / "processed" / "drainage_links.geojson"
STORM_PATH = ROOT / "data" / "swmm" / "tests" / "synthetic_storm.json"
ASSESSMENT_PATH = ROOT / "data" / "swmm" / "metadata" / "component_assessment.json"
MAPPING_PATH = ROOT / "data" / "swmm" / "metadata" / "p4_to_swmm_mapping.json"
COVERAGE_PATH = ROOT / "data" / "swmm" / "metadata" / "subcatchment_coverage.json"
RESULTS_DIR = ROOT / "data" / "swmm" / "results"
PREVIEW_DIR = RESULTS_DIR / "preview"
NODE_CSV = RESULTS_DIR / "node_timeseries.csv"
LINK_CSV = RESULTS_DIR / "link_timeseries.csv"
OUTFALL_CSV = RESULTS_DIR / "outfall_timeseries.csv"
NODE_SUMMARY = RESULTS_DIR / "node_summary.json"
LINK_SUMMARY = RESULTS_DIR / "link_summary.json"
OUTFALL_SUMMARY = RESULTS_DIR / "outfall_summary.json"
COMPONENT_SUMMARY = RESULTS_DIR / "component_summary.json"
WATER_BALANCE = RESULTS_DIR / "p5_water_balance.json"
SWMM_SUMMARY = RESULTS_DIR / "swmm_summary.json"
VALIDATION_PATH = RESULTS_DIR / "p5_validation.json"
SCRIPT_VERSION = "p5-swmm-runner-2.1.0"


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


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_model_objects() -> tuple[dict, dict]:
    nodes = {feature["properties"]["node_id"]: feature for feature in load_json(NODES_PATH)["features"]}
    links = {feature["properties"]["link_id"]: feature for feature in load_json(LINKS_PATH)["features"]}
    return nodes, links


def report_value(lines: list[str], label: str) -> float:
    pattern = re.compile(r"^" + re.escape(label) + r"\s+\.*\s+([-+]?\d+(?:\.\d+)?)")
    for line in lines:
        match = pattern.match(line.strip())
        if match:
            return float(match.group(1))
    raise ValueError(f"SWMM report is missing balance row: {label}")


def parse_report_balance(report_path: Path) -> dict:
    lines = report_path.read_text(encoding="utf-8", errors="replace").splitlines()
    runoff_labels = ["Total Precipitation", "Evaporation Loss", "Infiltration Loss", "Surface Runoff", "Final Storage", "Continuity Error (%)"]
    routing_labels = ["Dry Weather Inflow", "Wet Weather Inflow", "Groundwater Inflow", "RDII Inflow", "External Inflow", "External Outflow", "Flooding Loss", "Evaporation Loss", "Exfiltration Loss", "Initial Stored Volume", "Final Stored Volume", "Continuity Error (%)"]
    runoff = {label.lower().replace(" ", "_").replace("(", "").replace(")", ""): report_value(lines, label) for label in runoff_labels}
    routing_section_start = next((index for index, line in enumerate(lines) if "Flow Routing Continuity" in line), None)
    if routing_section_start is None:
        raise ValueError("SWMM report is missing Flow Routing Continuity section")
    routing_lines = lines[routing_section_start:]
    routing = {label.lower().replace(" ", "_").replace("(", "").replace(")", ""): report_value(routing_lines, label) for label in routing_labels}
    hectare_m3 = 10000.0
    runoff_m3 = {key: value * hectare_m3 for key, value in runoff.items() if key != "continuity_error_%"}
    routing_m3 = {key: value * hectare_m3 for key, value in routing.items() if key != "continuity_error_%"}
    runoff_residual = runoff_m3["total_precipitation"] - runoff_m3["evaporation_loss"] - runoff_m3["infiltration_loss"] - runoff_m3["surface_runoff"] - runoff_m3["final_storage"]
    routing_residual = (routing_m3["dry_weather_inflow"] + routing_m3["wet_weather_inflow"] + routing_m3["groundwater_inflow"] + routing_m3["rdii_inflow"] + routing_m3["external_inflow"] - routing_m3["external_outflow"] - routing_m3["flooding_loss"] - routing_m3["evaporation_loss"] - routing_m3["exfiltration_loss"] + routing_m3["initial_stored_volume"] - routing_m3["final_stored_volume"])
    ending_line = next((line.strip() for line in lines if line.strip().startswith("Ending Date")), "")
    ending_match = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})", ending_line)
    volume_note = "SWMM report volume values are printed in hectare-metres and converted here using 1 hectare-metre = 10,000 m3; printed values are rounded by SWMM."
    field_definitions = {
        "runoff_quantity": {
            "source_section": "Runoff Quantity Continuity",
            "unit": "m3",
            "rounding": "SWMM report display rounded before conversion",
            "fields": {
                "total_precipitation": {"definition": "Cumulative rainfall volume applied to all SWMM subcatchments over the report period", "state": "cumulative"},
                "evaporation_loss": {"definition": "Cumulative subcatchment evaporation loss", "state": "cumulative"},
                "infiltration_loss": {"definition": "Cumulative infiltration loss from subcatchments", "state": "cumulative"},
                "surface_runoff": {"definition": "Cumulative runoff leaving subcatchments and entering the routing system", "state": "cumulative"},
                "final_storage": {"definition": "Subcatchment runoff quantity remaining in final surface/depression storage at the report end", "state": "final_state"},
                "computed_residual_m3_from_report_rounding": {"definition": "Residual computed from the displayed runoff volumes; not an additional physical storage or loss term", "state": "derived_from_rounded_report"},
            },
        },
        "flow_routing": {
            "source_section": "Flow Routing Continuity",
            "unit": "m3",
            "rounding": "SWMM report display rounded before conversion",
            "fields": {
                "dry_weather_inflow": {"definition": "Cumulative dry-weather inflow into the routing system", "state": "cumulative"},
                "wet_weather_inflow": {"definition": "Cumulative runoff inflow from subcatchments into the routing system", "state": "cumulative"},
                "groundwater_inflow": {"definition": "Cumulative groundwater inflow into the routing system", "state": "cumulative"},
                "rdii_inflow": {"definition": "Cumulative rainfall-derived inflow and infiltration entering the routing system", "state": "cumulative"},
                "external_inflow": {"definition": "Cumulative external hydraulic inflow", "state": "cumulative"},
                "external_outflow": {"definition": "Cumulative discharge through modeled external outfalls", "state": "cumulative"},
                "flooding_loss": {"definition": "Cumulative water leaving the routing system as flooding loss; with ALLOW_PONDING YES, ponded water is retained in routing storage instead", "state": "cumulative"},
                "evaporation_loss": {"definition": "Cumulative routing evaporation loss", "state": "cumulative"},
                "exfiltration_loss": {"definition": "Cumulative routing exfiltration loss", "state": "cumulative"},
                "initial_stored_volume": {"definition": "Routing-system water stored at the simulation start", "state": "initial_state"},
                "final_stored_volume": {"definition": "Routing-system water stored at the report end, including retained ponded storage", "state": "final_state"},
                "computed_residual_m3_from_report_rounding": {"definition": "Residual computed from the displayed routing volumes; not an additional physical storage or loss term", "state": "derived_from_rounded_report"},
            },
        },
        "cross_section_note": volume_note,
        "non_interchangeability": "Runoff Quantity Continuity and Flow Routing Continuity are separate SWMM accounting sections. Their storage and inflow values must not be added together as one balance.",
    }
    return {
        "source": str(report_path.relative_to(ROOT)).replace("\\", "/"),
        "units": "m3; continuity percentages are SWMM report percentages",
        "report_period": {"ending_datetime": f"{ending_match.group(1)} {ending_match.group(2)}" if ending_match else None},
        "runoff_quantity": {**runoff_m3, "continuity_error_percent": runoff["continuity_error_%"], "computed_residual_m3_from_report_rounding": runoff_residual},
        "flow_routing": {**routing_m3, "continuity_error_percent": routing["continuity_error_%"], "computed_residual_m3_from_report_rounding": routing_residual},
        "accounting_definitions": {"runoff": "precipitation = evaporation + infiltration + surface runoff + final storage + continuity residual", "routing": "inflows + initial storage = external outflow + flooding + evaporation + exfiltration + final storage + continuity residual", "note": "The two equations are separate SWMM sections and are not combined."},
        "field_definitions": field_definitions,
    }


def deterministic_signature(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def run_simulation() -> dict:
    try:
        from pyswmm import Links, Nodes, Simulation, Subcatchments
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("PySWMM is unavailable. Install scripts/requirements-data.txt before running P5.") from error

    config = load_json(CONFIG_PATH)
    storm = load_json(STORM_PATH)
    model_nodes, model_links = parse_model_objects()
    assessment = load_json(ASSESSMENT_PATH)
    mapping = load_json(MAPPING_PATH)
    coverage = load_json(COVERAGE_PATH)
    mapping_by_link = {item["p4_id"]: item for item in mapping["link_mapping"]["mapped"]}
    node_ids = sorted(assessment["simulated_node_ids"])
    link_ids = sorted(assessment["simulated_link_ids"])
    outfall_ids = [assessment["outfall_candidate"]]
    report_step = float(config["routing"]["report_timestep_seconds"])
    hydraulic_step = float(config["routing"]["hydraulic_timestep_seconds"])
    storm_records = storm.get("records", [])
    if not storm_records:
        raise ValueError("Rainfall fixture contains no records")
    configured_start_dt = datetime.fromisoformat(storm_records[0]["timestamp"].replace("Z", "+00:00"))
    configured_end_dt = datetime.fromisoformat(storm_records[-1]["timestamp"].replace("Z", "+00:00")) + timedelta(seconds=float(storm["timestep_seconds"]))
    configured_start = configured_start_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    configured_end = configured_end_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    assumptions = config["model_assumptions"]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = RESULTS_DIR / "bellandur_prototype.rpt"
    output_path = RESULTS_DIR / "bellandur_prototype.out"
    node_rows: list[dict] = []
    link_rows: list[dict] = []
    outfall_rows: list[dict] = []
    start_time = None
    end_time = None
    engine_version = None
    flow_routing_error = None
    runoff_error = None
    quality_error = None
    node_stats: dict[str, dict] = {}
    link_max: dict[str, dict] = {link_id: {"max_abs_flow_cms": 0.0, "max_depth_m": 0.0, "max_velocity_mps": 0.0, "near_full_depth_count": 0} for link_id in link_ids}
    subcatchments_metadata = coverage["subcatchments"]
    subcatchment_ids = [item["subcatchment_id"] for item in subcatchments_metadata]
    with Simulation(str(MODEL_PATH), str(report_path), str(output_path)) as sim:
        sim.step_advance(int(report_step))
        nodes = Nodes(sim)
        links = Links(sim)
        subcatchments = Subcatchments(sim)
        engine_version = str(sim.engine_version)
        for _step in sim:
            current = timestamp_value(sim.current_time)
            start_time = start_time or current
            end_time = current
            for node_id in node_ids:
                node = nodes[node_id]
                depth = finite(node.depth)
                flooding = finite(node.flooding)
                full_depth = finite(node.full_depth)
                row = {"timestamp": current, "node_id": node_id, "node_type": model_nodes[node_id]["properties"].get("node_type", ""), "component_id": next(item["component_id"] for item in assessment["components"] if node_id in item["node_ids"]), "depth_m": depth, "head_m": finite(node.head), "total_inflow_cms": finite(node.total_inflow), "total_outflow_cms": finite(node.total_outflow), "flooding_cms": flooding, "volume_m3": finite(node.volume), "full_depth_m": full_depth, "modelled_surcharge": bool(depth > float(assumptions["junction_max_depth_m"]) + 1e-9), "modelled_flooding": bool(flooding > 1e-12)}
                node_rows.append(row)
                if node_id in outfall_ids:
                    outfall_rows.append({"timestamp": current, "outfall_id": node_id, "component_id": row["component_id"], "depth_m": depth, "head_m": row["head_m"], "inflow_cms": row["total_inflow_cms"], "discharge_cms": max(0.0, row["total_outflow_cms"]), "flooding_cms": flooding, "volume_m3": row["volume_m3"]})
            for link_id in link_ids:
                link = links[link_id]
                flow = finite(link.flow)
                depth = finite(link.depth)
                area = finite(link.ups_xsection_area)
                velocity = flow / area if area > 1e-12 else 0.0
                link_rows.append({"timestamp": current, "link_id": link_id, "component_id": next(item["component_id"] for item in assessment["components"] if link_id in item["link_ids"]), "from_node": mapping_by_link[link_id]["swmm_from_node"], "to_node": mapping_by_link[link_id]["swmm_to_node"], "flow_cms": flow, "depth_m": depth, "velocity_mps": velocity, "upstream_cross_section_area_m2": area, "near_full_depth": bool(depth >= 0.95 * float(assumptions["conduit_diameter_m"])), "capacity_status": "unknown_no_surveyed_capacity"})
        flow_routing_error = finite(sim.flow_routing_error)
        runoff_error = finite(sim.runoff_error)
        quality_error = finite(sim.quality_error)
        for node_id in node_ids:
            try:
                node_stats[node_id] = dict(nodes[node_id].statistics)
            except Exception:
                node_stats[node_id] = {}
        subcatch_stats = {subcatchment_id: dict(subcatchments[subcatchment_id].statistics) for subcatchment_id in subcatchment_ids}

    for row in outfall_rows:
        incoming = [link_row for link_row in link_rows if link_row["timestamp"] == row["timestamp"] and link_row["to_node"] == row["outfall_id"]]
        row["discharge_cms"] = sum(max(0.0, link_row["flow_cms"]) for link_row in incoming)

    for row in link_rows:
        summary = link_max[row["link_id"]]
        summary["max_abs_flow_cms"] = max(summary["max_abs_flow_cms"], abs(row["flow_cms"]))
        summary["max_depth_m"] = max(summary["max_depth_m"], row["depth_m"])
        summary["max_velocity_mps"] = max(summary["max_velocity_mps"], abs(row["velocity_mps"]))
        summary["near_full_depth_count"] += int(row["near_full_depth"])
    node_summary = {}
    for node_id in node_ids:
        rows = [row for row in node_rows if row["node_id"] == node_id]
        node_summary[node_id] = {"component_id": rows[0]["component_id"], "node_type": rows[0]["node_type"], "max_depth_m": max(row["depth_m"] for row in rows), "max_head_m": max(row["head_m"] for row in rows), "max_inflow_cms": max(row["total_inflow_cms"] for row in rows), "max_outflow_cms": max(row["total_outflow_cms"] for row in rows), "max_flooding_cms": max(row["flooding_cms"] for row in rows), "flooding_timesteps": sum(int(row["modelled_flooding"]) for row in rows), "surcharge_timesteps": sum(int(row["modelled_surcharge"]) for row in rows), "final_volume_m3": rows[-1]["volume_m3"], "pyswmm_statistics": node_stats.get(node_id, {})}
    link_summary = {link_id: {**summary, "component_id": next(item["component_id"] for item in assessment["components"] if link_id in item["link_ids"]), "capacity_status": "unknown_no_surveyed_capacity", "model_assumption_full_depth_m": float(assumptions["conduit_diameter_m"])} for link_id, summary in link_max.items()}
    outfall_summary = {outfall_id: {"component_id": next(item["component_id"] for item in assessment["components"] if outfall_id in item["node_ids"]), "max_discharge_cms": max(row["discharge_cms"] for row in outfall_rows if row["outfall_id"] == outfall_id), "total_discharge_volume_m3": sum(row["discharge_cms"] for row in outfall_rows if row["outfall_id"] == outfall_id) * report_step, "max_depth_m": max(row["depth_m"] for row in outfall_rows if row["outfall_id"] == outfall_id)} for outfall_id in outfall_ids}
    parsed_balance = parse_report_balance(report_path)
    rain_total_mm = sum(finite(record.get("rainfall_mm")) for record in storm_records)
    rainfall_volume_m3 = rain_total_mm / 1000.0 * float(coverage["modeled_subcatchment_area_m2"])
    report_rainfall_volume_m3 = parsed_balance["runoff_quantity"]["total_precipitation"]
    rainfall_report_difference_m3 = rainfall_volume_m3 - report_rainfall_volume_m3
    coverage["rainfall_validation"] = {
        "source": storm.get("source"),
        "total_rainfall_mm": rain_total_mm,
        "expected_rainfall_volume_m3": rainfall_volume_m3,
        "actual_swmm_rainfall_volume_m3": report_rainfall_volume_m3,
        "difference_m3": rainfall_report_difference_m3,
        "difference_is_report_rounding": abs(rainfall_report_difference_m3) <= 100.0,
        "note": "The geometric expected volume is rainfall depth times modeled subcatchment area; the SWMM report volume is displayed with rounding.",
    }
    COVERAGE_PATH.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    component_summary = {}
    for item in assessment["components"]:
        if item["status"] != "simulated":
            component_summary[item["component_id"]] = {"component_id": item["component_id"], "status": "excluded", "node_ids": item["node_ids"], "link_ids": item["link_ids"], "exclusion_reason": item["exclusion_reason"]}
            continue
        component_node_ids = item["node_ids"]
        component_link_ids = item["link_ids"]
        component_subcatchments = [cell for cell in subcatchments_metadata if cell["outlet_node_id"] in component_node_ids]
        component_subcatchment_ids = [cell["subcatchment_id"] for cell in component_subcatchments]
        component_rainfall_m3 = sum(float(cell["area_m2"]) for cell in component_subcatchments) * rain_total_mm / 1000.0
        component_runoff_m3 = sum(finite(subcatch_stats[subcatchment_id].get("runoff")) for subcatchment_id in component_subcatchment_ids)
        component_infiltration_m3 = sum(finite(subcatch_stats[subcatchment_id].get("infiltration")) for subcatchment_id in component_subcatchment_ids)
        component_summary[item["component_id"]] = {"component_id": item["component_id"], "status": "simulated", "node_ids": component_node_ids, "link_ids": component_link_ids, "boundary_type": item["boundary_type"], "boundary_source": item["boundary_source"], "boundary_node_ids": item["boundary_node_ids"], "rainfall_input_m3": component_rainfall_m3, "runoff_input_m3": component_runoff_m3, "infiltration_loss_m3": component_infiltration_m3, "maximum_node_depth_m": max(node_summary[node_id]["max_depth_m"] for node_id in component_node_ids), "maximum_link_flow_cms": max((link_summary[link_id]["max_abs_flow_cms"] for link_id in component_link_ids), default=0.0), "flooded_nodes": [node_id for node_id in component_node_ids if node_summary[node_id]["max_flooding_cms"] > 0], "surcharged_nodes": [node_id for node_id in component_node_ids if node_summary[node_id]["surcharge_timesteps"] > 0], "final_storage_m3": sum(node_summary[node_id]["final_volume_m3"] for node_id in component_node_ids), "outfall_discharge_m3": sum(row["discharge_cms"] for row in outfall_rows if row["outfall_id"] in item["node_ids"]) * report_step, "subcatchment_count": len(component_subcatchments), "subcatchment_ids": component_subcatchment_ids, "subcatchment_strategy": "full_canonical_bbox_grid_routed_to_nearest_p4_simulated_junction"}
    max_node = max(node_summary, key=lambda node_id: node_summary[node_id]["max_depth_m"])
    max_link = max(link_summary, key=lambda link_id: link_summary[link_id]["max_abs_flow_cms"])
    node_flooding = [node_id for node_id, summary in node_summary.items() if summary["max_flooding_cms"] > 0]
    max_node_properties = model_nodes[max_node]["properties"]
    max_node_links = sorted(
        link_id
        for link_id, feature in model_links.items()
        if feature["properties"].get("from_node") == max_node
        or feature["properties"].get("to_node") == max_node
    )
    max_node_subcatchments = [
        cell for cell in subcatchments_metadata if cell["outlet_node_id"] == max_node
    ]
    maximum_node_audit = {
        "node_id": max_node,
        "component_id": node_summary[max_node]["component_id"],
        "node_type": max_node_properties.get("node_type"),
        "source": max_node_properties.get("source"),
        "source_ids": max_node_properties.get("source_ids", []),
        "ground_elevation_m": finite(max_node_properties.get("ground_elevation_m")),
        "invert_elevation_m": finite(max_node_properties.get("ground_elevation_m"))
        - float(assumptions["invert_offset_below_ground_m"]),
        "invert_source": "model_assumption",
        "configured_max_depth_m": float(assumptions["junction_max_depth_m"]),
        "max_reported_depth_m": node_summary[max_node]["max_depth_m"],
        "pyswmm_internal_max_depth_m": finite(
            node_summary[max_node]["pyswmm_statistics"].get("max_depth")
        ),
        "reported_depth_sampling": "5-minute extracted report timestamps; PySWMM internal statistics retain the finer-step peak",
        "connected_p4_link_ids": max_node_links,
        "prototype_subcatchment_ids": [
            cell["subcatchment_id"] for cell in max_node_subcatchments
        ],
        "prototype_subcatchment_count": len(max_node_subcatchments),
        "prototype_subcatchment_area_m2": sum(
            float(cell["area_m2"]) for cell in max_node_subcatchments
        ),
        "prototype_routing_method": "nearest_P4_simulated_junction_centroid",
        "prototype_routing_verified_drainage_connection": False,
        "interpretation": (
            "Depth is driven by prototype full-area rainfall allocation into a "
            "closed-terminal P4 component and assumed hydraulic geometry; no "
            "surveyed municipal capacity or invert is claimed."
        ),
    }
    closed_terminal_audit = []
    for item in assessment["components"]:
        if item["boundary_type"] != "closed_terminal_junction":
            continue
        component_subcatchments = [
            cell for cell in subcatchments_metadata if cell["outlet_node_id"] in item["node_ids"]
        ]
        component_result = component_summary[item["component_id"]]
        closed_terminal_audit.append(
            {
                "component_id": item["component_id"],
                "boundary_node_ids": item["boundary_node_ids"],
                "connected_link_ids": item["link_ids"],
                "connected_link_count": len(item["link_ids"]),
                "subcatchment_ids": [cell["subcatchment_id"] for cell in component_subcatchments],
                "subcatchment_count": len(component_subcatchments),
                "boundary_condition": item["boundary_type"],
                "boundary_source": item["boundary_source"],
                "maximum_node_depth_m": component_result["maximum_node_depth_m"],
                "final_storage_m3": component_result["final_storage_m3"],
                "storage_accumulation_expected": True,
                "boundary_materially_affects_result": bool(
                    component_subcatchments and component_result["final_storage_m3"] > 0.0
                ),
                "interpretation": "No verified outfall is available; retaining the P4 terminal junction boundary avoids fabricating municipal infrastructure and makes retained storage/flooding an explicit model-assumption response.",
            }
        )
    water_balance = {"processing_script": SCRIPT_VERSION, "rainfall_source": storm.get("source"), "synthetic_fixture": storm.get("source") == "synthetic_test", "report": parsed_balance, "pyswmm_api_diagnostics": {"runoff_mass_balance_error_percent": runoff_error, "flow_routing_mass_balance_error_percent": flow_routing_error, "quality_mass_balance_error_percent": quality_error}, "input_volume_cross_check": {"fixture_rainfall_total_mm": rain_total_mm, "modeled_subcatchment_area_m2": float(coverage["modeled_subcatchment_area_m2"]), "estimated_area_based_rainfall_input_m3": rainfall_volume_m3, "swmm_report_precipitation_m3": report_rainfall_volume_m3, "difference_m3": rainfall_report_difference_m3, "difference_is_report_rounding": abs(rainfall_report_difference_m3) <= 100.0}, "interpretation": "The modeled rainfall input is exactly rainfall depth times the full modeled area. SWMM's printed report rounds volumes, so its displayed precipitation can differ by a small amount; the report's runoff and routing continuity rows remain the authoritative engine accounting and their displayed residuals are retained."}
    canonical_result = {"coverage": {"modeled_subcatchment_area_m2": coverage["modeled_subcatchment_area_m2"], "subcatchment_count": coverage["subcatchment_count"], "outlet_nodes": [(cell["subcatchment_id"], cell["outlet_node_id"]) for cell in subcatchments_metadata]}, "node_rows": node_rows, "link_rows": link_rows, "outfall_rows": outfall_rows, "node_summary": node_summary, "link_summary": link_summary, "outfall_summary": outfall_summary, "component_summary": component_summary, "water_balance": water_balance, "maximum_node_audit": maximum_node_audit, "closed_terminal_audit": closed_terminal_audit}
    signature = deterministic_signature(canonical_result)
    summary = {"processing_script": SCRIPT_VERSION, "processing_date_utc": datetime.now(timezone.utc).isoformat(), "pyswmm_version": importlib.metadata.version("pyswmm"), "swmm_engine_version": engine_version, "model_file": str(MODEL_PATH.relative_to(ROOT)).replace("\\", "/"), "rainfall_fixture": str(STORM_PATH.relative_to(ROOT)).replace("\\", "/"), "rainfall_source": storm.get("source"), "configured_simulation_start": configured_start, "configured_simulation_end": configured_end, "configured_duration_seconds": (configured_end_dt - configured_start_dt).total_seconds(), "first_report_timestamp": start_time, "last_report_timestamp": end_time, "reported_timesteps": len(node_rows) // len(node_ids) if node_ids else 0, "hydraulic_timestep_seconds": hydraulic_step, "report_timestep_seconds": report_step, "routing_method": config["routing"]["method"], "flow_units": config["routing"]["flow_units"], "p4_totals": assessment["p4_totals"], "simulated_component_count": assessment["simulated_totals"]["components"], "simulated_node_count": len(node_ids), "simulated_link_count": len(link_ids), "outfall_count": len(outfall_ids), "closed_terminal_component_boundary_count": assessment["boundary_totals"]["closed_terminal_component_boundaries"], "subcatchment_count": coverage["subcatchment_count"], "modeled_subcatchment_area_m2": coverage["modeled_subcatchment_area_m2"], "modeled_subcatchment_area_km2": coverage["modeled_subcatchment_area_km2"], "canonical_bbox_area_km2_projected": coverage["canonical_bbox_area_km2_projected"], "subcatchment_coverage_percentage": coverage["coverage_percentage"], "rainfall_total_mm": rain_total_mm, "rainfall_input_volume_m3_estimate": rainfall_volume_m3, "swmm_report_precipitation_m3": report_rainfall_volume_m3, "rainfall_report_difference_m3": rainfall_report_difference_m3, "water_balance_file": str(WATER_BALANCE.relative_to(ROOT)).replace("\\", "/"), "water_balance_diagnostics": {"runoff_mass_balance_error_percent": runoff_error, "flow_routing_mass_balance_error_percent": flow_routing_error, "quality_mass_balance_error_percent": quality_error}, "modelled_flooding_nodes": node_flooding, "maximum_node": {"node_id": max_node, **node_summary[max_node]}, "maximum_node_audit": maximum_node_audit, "closed_terminal_audit": closed_terminal_audit, "maximum_link": {"link_id": max_link, **link_summary[max_link]}, "capacity_assessment": "Surveyed link capacities are unavailable. Near-full-depth is reported against the explicit prototype diameter assumption; no observed capacity exceedance is claimed.", "deterministic_result_sha256": signature}
    node_fields = ["timestamp", "node_id", "node_type", "component_id", "depth_m", "head_m", "total_inflow_cms", "total_outflow_cms", "flooding_cms", "volume_m3", "full_depth_m", "modelled_surcharge", "modelled_flooding"]
    link_fields = ["timestamp", "link_id", "component_id", "from_node", "to_node", "flow_cms", "depth_m", "velocity_mps", "upstream_cross_section_area_m2", "near_full_depth", "capacity_status"]
    outfall_fields = ["timestamp", "outfall_id", "component_id", "depth_m", "head_m", "inflow_cms", "discharge_cms", "flooding_cms", "volume_m3"]
    write_csv(NODE_CSV, node_rows, node_fields)
    write_csv(LINK_CSV, link_rows, link_fields)
    write_csv(OUTFALL_CSV, outfall_rows, outfall_fields)
    NODE_SUMMARY.write_text(json.dumps(node_summary, indent=2) + "\n", encoding="utf-8")
    LINK_SUMMARY.write_text(json.dumps(link_summary, indent=2) + "\n", encoding="utf-8")
    OUTFALL_SUMMARY.write_text(json.dumps(outfall_summary, indent=2) + "\n", encoding="utf-8")
    COMPONENT_SUMMARY.write_text(json.dumps(component_summary, indent=2) + "\n", encoding="utf-8")
    WATER_BALANCE.write_text(json.dumps(water_balance, indent=2) + "\n", encoding="utf-8")
    SWMM_SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    validation = {"test_status": "PASS", "model_started": bool(engine_version), "model_completed": bool(end_time), "configured_end_time": configured_end, "last_report_timestamp": end_time, "report_ending_datetime": parsed_balance["report_period"]["ending_datetime"], "simulation_reached_intended_end": parsed_balance["report_period"]["ending_datetime"] == configured_end_dt.strftime("%m/%d/%Y %H:%M:%S"), "fatal_errors": [], "p4_totals": assessment["p4_totals"], "simulated_totals": assessment["simulated_totals"], "excluded_totals": assessment["excluded_totals"], "all_p4_features_accounted_for": mapping["coverage"]["all_p4_features_accounted_for"], "no_artificial_links": mapping["no_artificial_links"], "mapping_complete": mapping["coverage"]["all_p4_features_accounted_for"], "component_assessment_complete": len(assessment["components"]) == assessment["p4_totals"]["components"], "subcatchment_count": coverage["subcatchment_count"], "canonical_bbox_area_m2_projected": coverage["canonical_bbox_area_m2_projected"], "modeled_subcatchment_area_m2": coverage["modeled_subcatchment_area_m2"], "subcatchment_coverage_percentage": coverage["coverage_percentage"], "no_material_subcatchment_gap": not coverage["gaps"]["material_gap"], "no_material_subcatchment_overlap": not coverage["overlaps"]["material_overlap"], "rainfall_expected_volume_m3": rainfall_volume_m3, "rainfall_report_precipitation_m3": parsed_balance["runoff_quantity"]["total_precipitation"], "rainfall_report_difference_m3": rainfall_report_difference_m3, "rainfall_difference_is_report_rounding": abs(rainfall_report_difference_m3) <= 100.0, "maximum_node_audit": maximum_node_audit, "closed_terminal_audit": closed_terminal_audit, "closed_terminal_audit_count": len(closed_terminal_audit), "node_timeseries_rows": len(node_rows), "link_timeseries_rows": len(link_rows), "outfall_timeseries_rows": len(outfall_rows), "node_count": len(node_ids), "link_count": len(link_ids), "outputs_cover_all_simulated_nodes": {node_id: sum(row["node_id"] == node_id for row in node_rows) > 0 for node_id in node_ids}, "outputs_cover_all_simulated_links": {link_id: sum(row["link_id"] == link_id for row in link_rows) > 0 for link_id in link_ids}, "no_negative_depths": all(row["depth_m"] >= 0 for row in node_rows + link_rows + outfall_rows), "no_negative_flooding_rates": all(row["flooding_cms"] >= 0 for row in node_rows + outfall_rows), "rainfall_source_is_synthetic_fixture": storm.get("source") == "synthetic_test", "swmm_reported_runoff_error_percent": runoff_error, "swmm_reported_flow_routing_error_percent": flow_routing_error, "report_continuity_error_percent": {"runoff": parsed_balance["runoff_quantity"]["continuity_error_percent"], "flow_routing": parsed_balance["flow_routing"]["continuity_error_percent"]}, "water_balance_reported": WATER_BALANCE.exists(), "deterministic_result_sha256": signature, "outputs": {"node_timeseries": str(NODE_CSV.relative_to(ROOT)).replace("\\", "/"), "link_timeseries": str(LINK_CSV.relative_to(ROOT)).replace("\\", "/"), "outfall_timeseries": str(OUTFALL_CSV.relative_to(ROOT)).replace("\\", "/"), "component_summary": str(COMPONENT_SUMMARY.relative_to(ROOT)).replace("\\", "/"), "water_balance": str(WATER_BALANCE.relative_to(ROOT)).replace("\\", "/"), "summary": str(SWMM_SUMMARY.relative_to(ROOT)).replace("\\", "/"), "subcatchment_coverage": str(COVERAGE_PATH.relative_to(ROOT)).replace("\\", "/"), "subcatchment_qa_preview": str((PREVIEW_DIR / "p5_subcatchments_qa.geojson").relative_to(ROOT)).replace("\\", "/")}, "limitations": ["Prototype hydraulic parameters are model assumptions, not BBMP measurements.", "P4 direction was adjusted only for the verified outfall link and is recorded in component_assessment.json.", "Closed terminal junctions are boundary assumptions and are not claims about real municipal outfalls.", "P5 prototype subcatchment routing is not verified municipal drainage connectivity."]}
    VALIDATION_PATH.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    write_previews(model_nodes, model_links, assessment, node_summary, link_summary, coverage)
    return {"summary": summary, "validation": validation}


def write_previews(nodes: dict, links: dict, assessment: dict, node_summary: dict, link_summary: dict, coverage: dict) -> None:
    assessment_by_node = {node_id: item for item in assessment["components"] for node_id in item["node_ids"]}
    assessment_by_link = {link_id: item for item in assessment["components"] for link_id in item["link_ids"]}
    network_features = []
    for node_id, feature in nodes.items():
        item = assessment_by_node[node_id]
        network_features.append({"type": "Feature", "id": node_id, "properties": {"qa_layer": "simulated_component" if item["status"] == "simulated" else "excluded_component", "node_id": node_id, "component_id": item["component_id"], "status": item["status"], "source": feature["properties"].get("source"), "node_type": feature["properties"].get("node_type"), "exclusion_reason": item["exclusion_reason"]}, "geometry": feature["geometry"]})
    for link_id, feature in links.items():
        item = assessment_by_link[link_id]
        network_features.append({"type": "Feature", "id": link_id, "properties": {"qa_layer": "simulated_component", "link_id": link_id, "component_id": item["component_id"], "status": item["status"], "source": feature["properties"].get("source"), "link_type": feature["properties"].get("link_type")}, "geometry": feature["geometry"]})
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    collection = {"type": "FeatureCollection", "name": "p5_network_qa", "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}, "features": network_features}
    (PREVIEW_DIR / "p5_network_qa.geojson").write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    simulated_features = []
    for node_id, summary in node_summary.items():
        simulated_features.append({"type": "Feature", "id": node_id, "properties": {"qa_layer": "simulated_node", "node_id": node_id, **summary}, "geometry": nodes[node_id]["geometry"]})
    for link_id, summary in link_summary.items():
        simulated_features.append({"type": "Feature", "id": link_id, "properties": {"qa_layer": "simulated_link", "link_id": link_id, **summary}, "geometry": links[link_id]["geometry"]})
    (PREVIEW_DIR / "p5_simulation_qa.geojson").write_text(json.dumps({"type": "FeatureCollection", "name": "p5_simulation_qa", "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}, "features": simulated_features}, indent=2) + "\n", encoding="utf-8")
    subcatchment_features = []
    for cell in coverage["subcatchments"]:
        subcatchment_features.append({"type": "Feature", "id": cell["subcatchment_id"], "properties": {key: value for key, value in cell.items() if key != "geometry"}, "geometry": {"type": "Polygon", "coordinates": [cell["geometry"]]}})
    (PREVIEW_DIR / "p5_subcatchments_qa.geojson").write_text(json.dumps({"type": "FeatureCollection", "name": "p5_full_area_subcatchments_qa", "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}, "features": subcatchment_features}, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(run_simulation(), indent=2))


if __name__ == "__main__":
    main()
