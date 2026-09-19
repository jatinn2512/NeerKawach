"""Automated validation for the expanded P5 EPA SWMM/PySWMM layer."""

from __future__ import annotations

import csv
import json
import math
import re
import unittest
from pathlib import Path

from build_swmm_model import MODEL_PATH, build_model, load_json


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "swmm_model.json"
ASSESSMENT_PATH = ROOT / "data" / "swmm" / "metadata" / "component_assessment.json"
MAPPING_PATH = ROOT / "data" / "swmm" / "metadata" / "p4_to_swmm_mapping.json"
COVERAGE_PATH = ROOT / "data" / "swmm" / "metadata" / "subcatchment_coverage.json"
STORM_PATH = ROOT / "data" / "swmm" / "tests" / "synthetic_storm.json"
RESULTS_DIR = ROOT / "data" / "swmm" / "results"
NODE_CSV = RESULTS_DIR / "node_timeseries.csv"
LINK_CSV = RESULTS_DIR / "link_timeseries.csv"
OUTFALL_CSV = RESULTS_DIR / "outfall_timeseries.csv"
SUMMARY_PATH = RESULTS_DIR / "swmm_summary.json"
VALIDATION_PATH = RESULTS_DIR / "p5_validation.json"
WATER_BALANCE_PATH = RESULTS_DIR / "p5_water_balance.json"


class SwmmPrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [CONFIG_PATH, MODEL_PATH, ASSESSMENT_PATH, MAPPING_PATH, COVERAGE_PATH, STORM_PATH, NODE_CSV, LINK_CSV, OUTFALL_CSV, SUMMARY_PATH, VALIDATION_PATH, WATER_BALANCE_PATH]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise unittest.SkipTest("P5 model/run artifacts are missing: " + ", ".join(missing))
        cls.config = load_json(CONFIG_PATH)
        cls.assessment = load_json(ASSESSMENT_PATH)
        cls.mapping = load_json(MAPPING_PATH)
        cls.coverage = load_json(COVERAGE_PATH)
        cls.storm = load_json(STORM_PATH)
        cls.summary = load_json(SUMMARY_PATH)
        cls.validation = load_json(VALIDATION_PATH)
        cls.water_balance = load_json(WATER_BALANCE_PATH)

    def test_full_p4_coverage_and_component_preservation(self):
        self.assertEqual(self.assessment["p4_totals"], {"nodes": 91, "links": 45, "components": 46})
        self.assertEqual(self.assessment["simulated_totals"], {"components": 31, "nodes": 76, "links": 45})
        self.assertEqual(self.assessment["excluded_totals"], {"components": 15, "nodes": 15, "links": 0})
        self.assertEqual(len(self.assessment["components"]), 46)
        self.assertEqual(self.assessment["excluded_component_ids"], [f"component_{index:03d}" for index in range(32, 47)])

    def test_mapping_accounts_for_every_p4_feature(self):
        self.assertTrue(self.mapping["coverage"]["all_p4_features_accounted_for"])
        self.assertEqual(len(self.mapping["node_mapping"]["mapped"]), 76)
        self.assertEqual(len(self.mapping["node_mapping"]["excluded"]), 15)
        self.assertEqual(len(self.mapping["link_mapping"]["mapped"]), 45)
        self.assertEqual(self.mapping["link_mapping"]["excluded"], [])
        self.assertTrue(self.mapping["no_artificial_links"])

    def test_full_canonical_subcatchment_coverage(self):
        self.assertEqual(self.coverage["subcatchment_count"], 81)
        self.assertEqual(len(self.coverage["subcatchments"]), 81)
        self.assertGreaterEqual(self.coverage["coverage_percentage"], 99.5)
        self.assertFalse(self.coverage["gaps"]["material_gap"])
        self.assertFalse(self.coverage["overlaps"]["material_overlap"])
        rainfall_validation = self.coverage["rainfall_validation"]
        self.assertEqual(rainfall_validation["source"], "synthetic_test")
        self.assertAlmostEqual(rainfall_validation["total_rainfall_mm"], 40.0)
        self.assertAlmostEqual(
            rainfall_validation["expected_rainfall_volume_m3"],
            40.0 / 1000.0 * self.coverage["modeled_subcatchment_area_m2"],
        )
        self.assertAlmostEqual(
            rainfall_validation["actual_swmm_rainfall_volume_m3"],
            self.water_balance["report"]["runoff_quantity"]["total_precipitation"],
        )
        self.assertAlmostEqual(
            rainfall_validation["difference_m3"],
            rainfall_validation["expected_rainfall_volume_m3"]
            - rainfall_validation["actual_swmm_rainfall_volume_m3"],
        )
        self.assertTrue(rainfall_validation["difference_is_report_rounding"])
        self.assertAlmostEqual(
            self.coverage["modeled_subcatchment_area_m2"],
            self.coverage["canonical_bbox_area_m2_projected"],
            delta=1.0,
        )
        bbox = self.coverage["canonical_bbox"]
        ids = [cell["subcatchment_id"] for cell in self.coverage["subcatchments"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(
            all(
                bbox["min_lon"] <= point[0] <= bbox["max_lon"]
                and bbox["min_lat"] <= point[1] <= bbox["max_lat"]
                for cell in self.coverage["subcatchments"]
                for point in cell["geometry"]
            )
        )

    def test_model_subcatchments_match_coverage_metadata(self):
        text = MODEL_PATH.read_text(encoding="utf-8")
        subcatchment_section = text.split("[SUBCATCHMENTS]", 1)[1].split("[SUBAREAS]", 1)[0]
        subcatchment_rows = re.findall(r"^SC\d+\s+.*$", subcatchment_section, flags=re.MULTILINE)
        self.assertEqual(len(subcatchment_rows), self.coverage["subcatchment_count"])
        model_area_ha = sum(float(row.split()[3]) for row in subcatchment_rows)
        self.assertAlmostEqual(model_area_ha * 10000.0, self.coverage["modeled_subcatchment_area_m2"], delta=1.0)

    def test_components_without_outfalls_use_explicit_closed_boundaries(self):
        simulated = [item for item in self.assessment["components"] if item["status"] == "simulated"]
        self.assertEqual(sum(item["boundary_type"] == "verified_outfall" for item in simulated), 1)
        self.assertEqual(sum(item["boundary_type"] == "closed_terminal_junction" for item in simulated), 30)
        self.assertTrue(all(item["boundary_source"] == "model_assumption" for item in simulated if item["boundary_type"] == "closed_terminal_junction"))
        self.assertTrue(all(item["status"] == "excluded" and item["exclusion_reason"] for item in self.assessment["components"] if item["component_id"] in self.assessment["excluded_component_ids"]))

    def test_closed_terminal_audit_covers_all_assumed_boundaries(self):
        audit = self.validation["closed_terminal_audit"]
        self.assertEqual(self.validation["closed_terminal_audit_count"], 30)
        self.assertEqual(len(audit), 30)
        self.assertEqual({item["boundary_condition"] for item in audit}, {"closed_terminal_junction"})
        self.assertEqual({item["boundary_source"] for item in audit}, {"model_assumption"})
        self.assertTrue(all(item["connected_link_count"] > 0 for item in audit))
        self.assertTrue(all(item["storage_accumulation_expected"] for item in audit))
        self.assertTrue(all("interpretation" in item for item in audit))

    def test_model_has_all_simulated_nodes_and_links_without_cross_component_edges(self):
        text = MODEL_PATH.read_text(encoding="utf-8")
        self.assertIn("FLOW_ROUTING DYNWAVE", text)
        self.assertIn("ALLOW_PONDING YES", text)
        self.assertEqual(text.count("\nNODE drn_n_"), 76)
        self.assertEqual(text.count("\nLINK drn_l_"), 45)
        component_by_node = {node_id: item["component_id"] for item in self.assessment["components"] for node_id in item["node_ids"]}
        for link in self.mapping["link_mapping"]["mapped"]:
            self.assertEqual(component_by_node[link["p4_from_node"]], component_by_node[link["p4_to_node"]])

    def test_model_build_is_deterministic(self):
        original = MODEL_PATH.read_bytes()
        build_model()
        self.assertEqual(original, MODEL_PATH.read_bytes())

    def test_synthetic_fixture_is_explicit_and_valid(self):
        self.assertEqual(self.storm["source"], "synthetic_test")
        self.assertEqual(self.storm["units"], "mm_per_timestep")
        self.assertEqual(sum(record["rainfall_mm"] for record in self.storm["records"]), 40)
        self.assertTrue(all(record["rainfall_mm"] >= 0 for record in self.storm["records"]))

    def test_runtime_completed_and_outputs_cover_full_network(self):
        self.assertEqual(self.validation["test_status"], "PASS")
        self.assertTrue(self.validation["model_started"])
        self.assertTrue(self.validation["model_completed"])
        self.assertTrue(self.validation["simulation_reached_intended_end"])
        self.assertEqual(self.validation["fatal_errors"], [])
        self.assertEqual(self.validation["node_timeseries_rows"], 76 * 11)
        self.assertEqual(self.validation["link_timeseries_rows"], 45 * 11)
        self.assertEqual(self.validation["outfall_timeseries_rows"], 11)
        self.assertTrue(all(self.validation["outputs_cover_all_simulated_nodes"].values()))
        self.assertTrue(all(self.validation["outputs_cover_all_simulated_links"].values()))

    def test_extracted_hydraulic_values_are_finite_and_nonnegative_where_required(self):
        with NODE_CSV.open(newline="", encoding="utf-8") as handle:
            node_rows = list(csv.DictReader(handle))
        with LINK_CSV.open(newline="", encoding="utf-8") as handle:
            link_rows = list(csv.DictReader(handle))
        with OUTFALL_CSV.open(newline="", encoding="utf-8") as handle:
            outfall_rows = list(csv.DictReader(handle))
        for row in node_rows:
            for key in ("depth_m", "head_m", "total_inflow_cms", "total_outflow_cms", "flooding_cms", "volume_m3"):
                self.assertTrue(math.isfinite(float(row[key])))
            self.assertGreaterEqual(float(row["depth_m"]), 0.0)
            self.assertGreaterEqual(float(row["flooding_cms"]), 0.0)
        for row in link_rows:
            for key in ("flow_cms", "depth_m", "velocity_mps", "upstream_cross_section_area_m2"):
                self.assertTrue(math.isfinite(float(row[key])))
            self.assertGreaterEqual(float(row["depth_m"]), 0.0)
        self.assertTrue(all(float(row["discharge_cms"]) >= 0 for row in outfall_rows))

    def test_water_balance_is_reported_without_false_zero_claim(self):
        self.assertIn("runoff_quantity", self.water_balance["report"])
        self.assertIn("flow_routing", self.water_balance["report"])
        expected_rainfall = 40.0 / 1000.0 * self.coverage["modeled_subcatchment_area_m2"]
        reported_rainfall = self.water_balance["report"]["runoff_quantity"]["total_precipitation"]
        self.assertAlmostEqual(reported_rainfall, expected_rainfall, delta=100.0)
        self.assertEqual(self.water_balance["input_volume_cross_check"]["difference_m3"], expected_rainfall - reported_rainfall)
        self.assertTrue(self.water_balance["input_volume_cross_check"]["difference_is_report_rounding"])
        self.assertEqual(self.validation["report_continuity_error_percent"], {"runoff": -0.143, "flow_routing": 0.11})
        definitions = self.water_balance["report"]["field_definitions"]
        self.assertEqual(definitions["runoff_quantity"]["source_section"], "Runoff Quantity Continuity")
        self.assertEqual(definitions["flow_routing"]["source_section"], "Flow Routing Continuity")
        self.assertEqual(definitions["runoff_quantity"]["fields"]["final_storage"]["state"], "final_state")
        self.assertEqual(definitions["flow_routing"]["fields"]["wet_weather_inflow"]["state"], "cumulative")
        self.assertIn("must not be added together", definitions["non_interchangeability"])

    def test_maximum_node_audit_is_explicit(self):
        audit = self.summary["maximum_node_audit"]
        self.assertEqual(audit["node_id"], self.summary["maximum_node"]["node_id"])
        self.assertEqual(audit["source"], "government_dataset")
        self.assertEqual(audit["invert_source"], "model_assumption")
        self.assertEqual(audit["prototype_routing_verified_drainage_connection"], False)
        self.assertGreater(audit["prototype_subcatchment_count"], 0)
        self.assertAlmostEqual(audit["max_reported_depth_m"], self.summary["maximum_node"]["max_depth_m"])
        self.assertGreaterEqual(audit["pyswmm_internal_max_depth_m"], audit["max_reported_depth_m"])
        self.assertIn("5-minute extracted report timestamps", audit["reported_depth_sampling"])

    def test_deterministic_runtime_signature(self):
        from run_swmm import run_simulation

        first = run_simulation()["summary"]["deterministic_result_sha256"]
        second = run_simulation()["summary"]["deterministic_result_sha256"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
