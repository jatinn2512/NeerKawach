"""Acceptance tests for the P6 surface-water/drainage coupling fixture."""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "coupling_model.json"
RESULTS = ROOT / "data" / "coupling" / "results"
CONNECTIONS = ROOT / "data" / "drainage" / "processed" / "surface_drainage_connections.geojson"
NODES = ROOT / "data" / "drainage" / "processed" / "drainage_nodes.geojson"
MAPPING = ROOT / "data" / "swmm" / "metadata" / "p4_to_swmm_mapping.json"
ASSESSMENT = ROOT / "data" / "swmm" / "metadata" / "component_assessment.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class CouplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [
            CONFIG,
            RESULTS / "surface_to_swmm_timeseries.csv",
            RESULTS / "swmm_to_surface_timeseries.csv",
            RESULTS / "swmm_node_timeseries.csv",
            RESULTS / "swmm_link_timeseries.csv",
            RESULTS / "coupling_summary.json",
            RESULTS / "coupling_water_balance.json",
            RESULTS / "p6_validation.json",
            CONNECTIONS,
            NODES,
            MAPPING,
            ASSESSMENT,
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise unittest.SkipTest("P6 coupling run has not completed: " + ", ".join(missing))
        cls.config = load_json(CONFIG)
        cls.connections = load_json(CONNECTIONS)["features"]
        cls.nodes = load_json(NODES)["features"]
        cls.mapping = load_json(MAPPING)
        cls.assessment = load_json(ASSESSMENT)
        cls.summary = load_json(RESULTS / "coupling_summary.json")
        cls.balance = load_json(RESULTS / "coupling_water_balance.json")
        cls.validation = load_json(RESULTS / "p6_validation.json")
        cls.transfer = load_csv(RESULTS / "surface_to_swmm_timeseries.csv")
        cls.overflow = load_csv(RESULTS / "swmm_to_surface_timeseries.csv")
        cls.node_rows = load_csv(RESULTS / "swmm_node_timeseries.csv")
        cls.link_rows = load_csv(RESULTS / "swmm_link_timeseries.csv")

    def test_generated_validation_passes(self):
        self.assertEqual(self.validation["test_status"], "PASS")
        self.assertTrue(self.validation["global_mass_balance_within_tolerance"])
        self.assertTrue(self.validation["overflow_accounting_within_tolerance"])

    def test_existing_p4_candidates_are_the_only_connections(self):
        ids = [feature["id"] for feature in self.connections]
        self.assertEqual(len(ids), 15)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(feature["properties"]["status"] == "candidate_only_no_transfer_simulated" for feature in self.connections))

    def test_connection_references_are_valid(self):
        p4_nodes = {feature["properties"]["node_id"] for feature in self.nodes}
        swmm_nodes = {item["swmm_id"] for item in self.mapping["node_mapping"]["mapped"]}
        for feature in self.connections:
            node_id = feature["properties"]["drainage_node_id"]
            self.assertIn(node_id, p4_nodes)
            self.assertIn(node_id, swmm_nodes)
            self.assertTrue(feature["properties"]["surface_cell_id"])

    def test_transfer_is_bounded_and_nonnegative(self):
        for row in self.transfer:
            transfer = float(row["transfer_volume_m3"])
            self.assertGreaterEqual(transfer, 0.0)
            self.assertLessEqual(transfer, float(row["pre_transfer_surface_water_m3"]) + 1e-9)
            self.assertLessEqual(transfer, float(row["configured_transfer_limit_m3"]) + 1e-9)

    def test_output_timestep_completeness(self):
        self.assertEqual(len(self.transfer), 12 * 15)
        self.assertEqual(len(self.node_rows), 120 * self.assessment["simulated_totals"]["nodes"])
        self.assertEqual(len(self.link_rows), 120 * self.assessment["simulated_totals"]["links"])
        self.assertEqual(len({row["timestamp"] for row in self.node_rows}), 120)
        self.assertEqual(len({row["timestamp"] for row in self.link_rows}), 120)

    def test_overflow_is_fully_partitioned(self):
        flooding = sum(float(row["flooding_cms"]) * 30.0 for row in self.node_rows)
        overflow = sum(float(row["overflow_volume_m3"]) for row in self.overflow)
        returned = sum(float(row["returned_to_surface_volume_m3"]) for row in self.overflow)
        unmapped = sum(float(row["unmapped_overflow_volume_m3"]) for row in self.overflow)
        self.assertAlmostEqual(flooding, overflow, places=6)
        self.assertAlmostEqual(overflow, returned + unmapped, places=6)

    def test_surface_and_drainage_balances_are_reported(self):
        self.assertAlmostEqual(self.balance["surface_domain"]["residual_m3"], 0.0, places=6)
        self.assertAlmostEqual(self.balance["drainage_domain"]["overflow_accounting_residual_m3"], 0.0, places=6)
        self.assertAlmostEqual(self.balance["coupled_domain"]["unexplained_residual_m3"], 0.0, places=6)
        self.assertGreater(abs(self.balance["coupled_domain"]["hydraulic_continuity_residual_m3"]), 0.0)

    def test_rainfall_is_owned_by_p3_only(self):
        self.assertTrue(self.config["architecture"]["p5_subcatchment_rainfall_disabled"])
        model = (ROOT / "data" / "coupling" / "input" / "bellandur_coupled_zero_rain.inp").read_text(encoding="utf-8")
        values = [float(line.split()[-1]) for line in model.splitlines() if line.startswith("SyntheticStorm")]
        self.assertTrue(values)
        self.assertTrue(all(value == 0.0 for value in values))

    def test_p5_provenance_is_preserved(self):
        self.assertEqual(self.assessment["simulated_totals"]["nodes"], 76)
        self.assertEqual(self.assessment["simulated_totals"]["links"], 45)
        self.assertEqual(self.assessment["boundary_totals"]["closed_terminal_component_boundaries"], 30)
        self.assertEqual(self.summary["p5_maximum_node_context"], "drn_n_00044 remains assumption-driven; node depth is not converted directly to street depth.")


if __name__ == "__main__":
    unittest.main()
