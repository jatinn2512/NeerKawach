import unittest
from dataclasses import replace

import route_flood_safe as routing


class RoadGeometryTests(unittest.TestCase):
    def test_forward_and_reverse_preserve_bend_and_length(self):
        a, bend, b = (77., 13.), (77.001, 13.001), (77.002, 13.)
        wkt = "LINESTRING (77 13, 77.001 13.001, 77.002 13)"
        fwd = routing.parse_wkt_linestring(wkt, a, b)
        rev = routing.parse_wkt_linestring(wkt, b, a)
        self.assertEqual(fwd, [a, bend, b])
        self.assertEqual(rev, list(reversed(fwd)))
        self.assertAlmostEqual(routing.polyline_length_m(fwd), routing.polyline_length_m(rev), places=8)

    def test_unsorted_multipart(self):
        text = "MULTILINESTRING ((77.002 13,77.001 13.001),(77 13,77.001 13.001))"
        self.assertEqual(routing.parse_wkt_linestring(text, (77, 13), (77.002, 13)),
                         [(77, 13), (77.001, 13.001), (77.002, 13)])

    def test_unavailable_or_ambiguous(self):
        for wkt in (None, "POINT (77 13)", "LINESTRING (nan 13,77.002 13)", "LINESTRING(0 0,1 1)",
                    "MULTILINESTRING ((77 13,77.002 13),(76 13,76.002 13))"):
            with self.subTest(wkt=wkt), self.assertRaises(ValueError):
                routing.parse_wkt_linestring(wkt, (77, 13), (77.002, 13))

    def test_graph_and_route_export(self):
        engine = routing.create_engine()
        for edge in engine.graph.edges.values():
            self.assertIsNone(edge.geometry_issue)
            self.assertLessEqual(routing.haversine_m(edge.geometry[0], engine.graph.nodes[edge.source]), .05)
            self.assertLessEqual(routing.haversine_m(edge.geometry[-1], engine.graph.nodes[edge.target]), .05)
            self.assertAlmostEqual(routing.polyline_length_m(edge.geometry), edge.length_m, places=6)
        start, end = (77.6576167, 12.9381234), (77.6502401, 12.9448164)
        result = engine.route(start, end, engine.impacts.timestamps[-2])
        output = engine.to_geojson(result)
        self.assertEqual(len(output["features"]), 2)
        for feature in output["features"]:
            props = feature["properties"]
            coords = feature["geometry"]["coordinates"]
            self.assertEqual(tuple(coords[0]), start)
            self.assertEqual(tuple(coords[-1]), end)
            self.assertAlmostEqual(routing.polyline_length_m(coords), props["distance_m"], places=6)
            self.assertEqual(props["edge_ids"], result[feature["id"]]["edge_ids"])
            self.assertFalse(props["includes_snap_connectors"])
        eid = result["baseline"]["edge_ids"][0]
        engine.graph.edges[eid] = replace(engine.graph.edges[eid], geometry=(), geometry_issue="missing geometry")
        feature = engine.to_geojson(result)["features"][0]
        self.assertIsNone(feature["geometry"])
        self.assertIn(eid, feature["properties"]["geometry_issues"])
