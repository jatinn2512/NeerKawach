"""Automated validation for the P4 drainage-network foundation."""

from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from build_drainage_network import (
    CONNECTIONS_GEOJSON,
    GRAPHML_PATH,
    LINKS_GEOJSON,
    METADATA_PATH,
    NODES_GEOJSON,
    OSM_RAW,
    VALIDATION_PATH,
    build_network,
    load_json,
)


ROOT = Path(__file__).resolve().parents[2]


class DrainageNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [NODES_GEOJSON, LINKS_GEOJSON, CONNECTIONS_GEOJSON, METADATA_PATH, VALIDATION_PATH, OSM_RAW]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise unittest.SkipTest("P4 builder has not been run: " + ", ".join(missing))
        cls.nodes = load_json(NODES_GEOJSON)["features"]
        cls.links = load_json(LINKS_GEOJSON)["features"]
        cls.connections = load_json(CONNECTIONS_GEOJSON)["features"]
        cls.validation = load_json(VALIDATION_PATH)

    def test_node_and_link_schema(self):
        node_required = {"node_id", "node_type", "source", "status"}
        link_required = {"link_id", "from_node", "to_node", "link_type", "source", "direction", "length_m"}
        self.assertTrue(all(node_required.issubset(feature["properties"]) for feature in self.nodes))
        self.assertTrue(all(link_required.issubset(feature["properties"]) for feature in self.links))

    def test_link_references_existing_nodes(self):
        node_ids = {feature["properties"]["node_id"] for feature in self.nodes}
        self.assertTrue(all(feature["properties"]["from_node"] in node_ids and feature["properties"]["to_node"] in node_ids for feature in self.links))

    def test_no_self_loops_and_valid_directions(self):
        for feature in self.links:
            properties = feature["properties"]
            self.assertNotEqual(properties["from_node"], properties["to_node"])
            self.assertEqual(properties["direction"], "forward_geometry_order")

    def test_geometry_and_crs_consistency(self):
        for collection in (NODES_GEOJSON, LINKS_GEOJSON, CONNECTIONS_GEOJSON):
            payload = load_json(collection)
            self.assertEqual(payload["crs"]["properties"]["name"], "EPSG:4326")
            for feature in payload["features"]:
                self.assertIn(feature["geometry"]["type"], {"Point", "LineString"})
                self.assertTrue(feature["geometry"]["coordinates"])

    def test_graph_connectivity_reporting(self):
        self.assertGreater(self.validation["connected_components"]["count"], 0)
        self.assertIn("orphan_nodes", self.validation)
        self.assertIn("unresolved_attributes", self.validation)

    def test_provenance_completeness(self):
        allowed = {"government_dataset", "observed_osm", "terrain_inferred", "synthetic_prototype"}
        self.assertTrue(all(feature["properties"]["source"] in allowed for feature in self.nodes))
        self.assertTrue(all(feature["properties"]["source"] in allowed for feature in self.links))
        self.assertIn("government_dataset", self.validation["node_source_counts"])

    def test_elevation_sampling_status(self):
        elevations = [feature["properties"].get("ground_elevation_m") for feature in self.nodes]
        self.assertTrue(all(value is None or isinstance(value, (int, float)) for value in elevations))
        self.assertEqual(self.validation["ground_elevation_sampled_nodes"], len(self.nodes))
        self.assertEqual(self.validation["unresolved_attributes"]["node_invert_elevation_m"], len(self.nodes))

    def test_surface_connections_reference_valid_nodes(self):
        node_ids = {feature["properties"]["node_id"] for feature in self.nodes}
        self.assertTrue(all(feature["properties"]["drainage_node_id"] in node_ids for feature in self.connections))
        self.assertTrue(all(feature["properties"]["status"] == "candidate_only_no_transfer_simulated" for feature in self.connections))

    def test_deterministic_rebuild(self):
        area = load_json(ROOT / "config" / "study_area.json")
        payload = load_json(OSM_RAW)
        first = build_network(area, payload)
        second = build_network(area, payload)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_generated_validation_passes(self):
        self.assertEqual(self.validation["test_status"], "PASS")
        self.assertTrue(all(self.validation["checks"].values()))

    def test_graphml_is_parseable_and_references_nodes(self):
        root = ET.parse(GRAPHML_PATH).getroot()
        namespace = "{http://graphml.graphdrawing.org/xmlns}"
        graph = root.find(namespace + "graph")
        self.assertIsNotNone(graph)
        node_ids = {node.attrib["id"] for node in graph.findall(namespace + "node")}
        edges = graph.findall(namespace + "edge")
        self.assertEqual(len(node_ids), len(self.nodes))
        self.assertEqual(len(edges), len(self.links))
        self.assertTrue(all(edge.attrib["source"] in node_ids and edge.attrib["target"] in node_ids for edge in edges))


if __name__ == "__main__":
    unittest.main()
