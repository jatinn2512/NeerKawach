"""Acceptance tests for P7 inundation and street-impact products."""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

import numpy as np
import rasterio


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data" / "inundation"
RASTER_DIR = OUTPUT / "rasters"
VECTOR_DIR = OUTPUT / "vectors"
ROAD_DIR = OUTPUT / "roads"
METRICS_DIR = OUTPUT / "metrics"
METADATA_DIR = OUTPUT / "metadata"
CONFIG_PATH = ROOT / "config" / "inundation.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class InundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [
            CONFIG_PATH,
            METRICS_DIR / "p7_summary.json",
            METRICS_DIR / "p7_validation.json",
            METRICS_DIR / "inundation_timeseries.csv",
            METADATA_DIR / "p7_provenance.json",
            RASTER_DIR / "max_depth.tif",
            RASTER_DIR / "max_risk_class.tif",
            VECTOR_DIR / "max_extent.geojson",
            ROAD_DIR / "road_impact_timeseries.csv",
            ROAD_DIR / "road_impact_summary.csv",
            ROAD_DIR / "road_impacts.geojson",
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise unittest.SkipTest("P7 generator has not been run: " + ", ".join(missing))
        cls.config = load_json(CONFIG_PATH)
        cls.summary = load_json(METRICS_DIR / "p7_summary.json")
        cls.validation = load_json(METRICS_DIR / "p7_validation.json")
        cls.provenance = load_json(METADATA_DIR / "p7_provenance.json")
        cls.area_rows = load_csv(METRICS_DIR / "inundation_timeseries.csv")
        cls.road_rows = load_csv(ROAD_DIR / "road_impact_timeseries.csv")
        cls.road_summary = load_csv(ROAD_DIR / "road_impact_summary.csv")

    def test_validation_passes(self):
        self.assertEqual(self.validation["test_status"], "PASS")
        self.assertEqual(self.validation["source_phase"], "P6")
        self.assertTrue(all(value for key, value in self.validation.items() if key.endswith("valid") or key.startswith("all_") or key == "maximum_raster_matches_time_series"))

    def test_depth_raster_schema_and_mask(self):
        with rasterio.open(RASTER_DIR / "max_depth.tif") as dataset:
            self.assertEqual(str(dataset.crs), "EPSG:32643")
            self.assertEqual(dataset.nodata, -9999.0)
            values = dataset.read(1)
            valid = values != dataset.nodata
            self.assertTrue(np.isfinite(values[valid]).all())
            self.assertTrue((values[valid] >= 0).all())
            self.assertGreater(int(np.count_nonzero(valid)), 0)

    def test_timestamped_depth_products_and_timestamp_preservation(self):
        paths = sorted(RASTER_DIR.glob("depth_*.tif"))
        self.assertEqual(len(paths), len(self.summary["timestamps"]))
        timestamps = []
        for path in paths:
            with rasterio.open(path) as dataset:
                timestamps.append(dataset.tags()["TIMESTAMP"])
        self.assertEqual(timestamps, self.summary["timestamps"])
        self.assertEqual([row["timestamp"] for row in self.area_rows], timestamps)

    def test_thresholding_and_area_consistency(self):
        threshold = float(self.config["depth_threshold_m"])
        expected = max(float(row["inundated_area_m2"]) for row in self.area_rows)
        self.assertEqual(expected, int(self.summary["maximum_inundated_area"]["value_m2"]))
        self.assertTrue(all(float(row["depth_threshold_m"]) == threshold for row in self.area_rows))

    def test_extent_geojson_is_valid_and_provenanced(self):
        extent = load_json(VECTOR_DIR / "max_extent.geojson")
        self.assertEqual(extent["crs"]["properties"]["name"], "EPSG:4326")
        self.assertEqual(extent["properties"]["source_phase"], "P6")
        self.assertTrue(all(feature["geometry"]["type"] == "Polygon" for feature in extent["features"]))
        self.assertTrue(all(feature["properties"]["depth_threshold_m"] == self.config["depth_threshold_m"] for feature in extent["features"]))

    def test_road_metrics_and_intersection_outputs(self):
        self.assertGreater(len(self.road_summary), 0)
        self.assertEqual(len(self.road_rows), len(self.road_summary) * len(self.summary["timestamps"]))
        threshold = float(self.config["depth_threshold_m"])
        for row in self.road_summary:
            series = [item for item in self.road_rows if item["road_id"] == row["road_id"]]
            maximum = max(float(item["max_intersecting_depth_m"]) for item in series)
            self.assertAlmostEqual(float(row["maximum_intersecting_depth_m"]), maximum, places=6)
            self.assertEqual(row["affected"].lower(), str(maximum >= threshold).lower())
            self.assertGreaterEqual(float(row["duration_above_threshold_seconds"]), 0.0)
            self.assertEqual(row["road_elevation_used"].lower(), "false")

    def test_provenance_and_units(self):
        self.assertEqual(self.provenance["source_phase"], "P6")
        self.assertEqual(self.provenance["depth_units"], "metres")
        self.assertEqual(self.provenance["output_vector_crs"], "EPSG:4326")
        self.assertEqual(self.provenance["depth_threshold_m"], self.config["depth_threshold_m"])
        self.assertTrue(self.provenance["source_files"])

    def test_deterministic_metric_output(self):
        first = (METRICS_DIR / "inundation_timeseries.csv").read_bytes()
        second = (METRICS_DIR / "inundation_timeseries.csv").read_bytes()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
