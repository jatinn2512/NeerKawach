"""Offline acceptance tests for P8 flood-aware routing."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from route_flood_safe import RoutingEngine, classify_depth, load_graph, load_p7_impacts


ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "config/routing.json").read_text(encoding="utf-8"))
STUDY_AREA = json.loads((ROOT / "config/study_area.json").read_text(encoding="utf-8"))
P7_CONFIG = json.loads((ROOT / CONFIG["source_p7_config"]).read_text(encoding="utf-8"))


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = load_graph(ROOT / CONFIG["source_road_graph"])
        cls.impacts = load_p7_impacts(ROOT / CONFIG["source_p7_road_timeseries"], ROOT / CONFIG["source_p7_road_summary"])
        cls.engine = RoutingEngine(CONFIG, STUDY_AREA, cls.graph, cls.impacts)
        cls.timestamp = cls.impacts.timestamps[-1]
        cls.origin_node = sorted(cls.graph.nodes)[0]
        cls.destination_node = sorted(cls.graph.nodes)[-1]
        cls.origin = cls.graph.nodes[cls.origin_node]
        cls.destination = cls.graph.nodes[cls.destination_node]

    def test_graph_loading_preserves_directed_edges_and_attributes(self):
        self.assertGreater(len(self.graph.nodes), 0)
        self.assertGreater(len(self.graph.edges), 0)
        self.assertTrue(all(edge.road_id.startswith("way/") for edge in self.graph.edges.values()))
        self.assertTrue(all(edge.length_m > 0 for edge in self.graph.edges.values()))
        self.assertTrue(any(edge.oneway == "yes" for edge in self.graph.edges.values()))

    def test_p7_join_is_complete(self):
        join = self.engine.validate_join()
        self.assertTrue(join["complete_for_graph"])
        self.assertEqual(join["missing_summary_road_ids"], [])
        self.assertEqual(join["missing_timeseries_road_ids"], [])

    def test_flood_classification_and_threshold_provenance(self):
        self.assertEqual(classify_depth(0.0, CONFIG), "normal")
        self.assertEqual(classify_depth(0.05, CONFIG), "flooded_traversable")
        self.assertEqual(classify_depth(0.299999, CONFIG), "flooded_traversable")
        self.assertEqual(classify_depth(0.30, CONFIG), "closed")
        self.assertEqual(classify_depth(None, CONFIG), "data_unavailable")
        self.assertEqual(CONFIG["flooded_threshold_m"], P7_CONFIG["depth_threshold_m"])

    def test_edge_weighting_and_closure(self):
        edge = next(edge for edge in self.graph.edges.values() if self.engine.impact_for(edge, self.timestamp) and self.engine.impact_for(edge, self.timestamp).depth_m is not None)
        impact = self.engine.impact_for(edge, self.timestamp)
        normal_cost = self.engine.edge_cost(edge, self.timestamp, False)
        flood_cost = self.engine.edge_cost(edge, self.timestamp, True)
        self.assertEqual(normal_cost, edge.length_m)
        if classify_depth(impact.depth_m, CONFIG) == "closed":
            self.assertIsNone(flood_cost)
        elif classify_depth(impact.depth_m, CONFIG) == "flooded_traversable":
            self.assertGreater(flood_cost, normal_cost)

    def test_point_snapping(self):
        node_id, distance = self.engine.snap_point(self.origin)
        self.assertEqual(node_id, self.origin_node)
        self.assertAlmostEqual(distance, 0.0)

    def test_baseline_and_timestamp_specific_routing(self):
        first = self.engine.route(self.origin, self.destination, self.impacts.timestamps[0])
        last = self.engine.route(self.origin, self.destination, self.impacts.timestamps[-1])
        self.assertEqual(first["timestamp"], self.impacts.timestamps[0])
        self.assertEqual(last["timestamp"], self.impacts.timestamps[-1])
        self.assertIn(first["status"], {"ok", "no_flood_aware_route", "no_route"})
        self.assertIsNotNone(first["baseline"]["distance_m"])
        self.assertIsNotNone(last["baseline"]["distance_m"])

    def test_flood_aware_route_respects_closed_edges(self):
        result = self.engine.route(self.origin, self.destination, self.timestamp)
        for edge_id in result["flood_aware"]["edge_ids"]:
            self.assertNotEqual(self.engine.edge_state(self.graph.edges[edge_id], self.timestamp), "closed")
            self.assertNotEqual(self.engine.edge_state(self.graph.edges[edge_id], self.timestamp), "data_unavailable")

    def test_invalid_timestamp_and_no_route_handling(self):
        with self.assertRaises(ValueError):
            self.engine.route(self.origin, self.destination, "2099-01-01T00:00:00Z")
        with self.assertRaises(ValueError):
            self.engine.snap_point((0.0, 0.0))
        candidates = sorted(self.graph.nodes)
        no_route = None
        for source_id in (candidates[0], candidates[10], candidates[-10], candidates[-1]):
            for target_id in (candidates[0], candidates[10], candidates[-10], candidates[-1]):
                if source_id == target_id:
                    continue
                result = self.engine.route(self.graph.nodes[source_id], self.graph.nodes[target_id], self.timestamp)
                if result["status"] == "no_route":
                    no_route = result
                    break
            if no_route is not None:
                break
        self.assertIsNotNone(no_route)
        self.assertIsNone(no_route["baseline"]["distance_m"])

    def test_deterministic_route_and_valid_geojson(self):
        first = self.engine.route(self.origin, self.destination, self.timestamp)
        second = self.engine.route(self.origin, self.destination, self.timestamp)
        self.assertEqual(first, second)
        output = self.engine.to_geojson(first)
        self.assertEqual(output["crs"]["properties"]["name"], "EPSG:4326")
        for feature in output["features"]:
            self.assertEqual(feature["geometry"]["type"], "LineString")
            self.assertGreaterEqual(len(feature["geometry"]["coordinates"]), 2)


if __name__ == "__main__":
    unittest.main()
