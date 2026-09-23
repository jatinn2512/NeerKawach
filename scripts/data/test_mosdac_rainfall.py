"""Validation tests for the locally acquired MOSDAC historical rainfall set."""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

import rasterio

from ingest_mosdac_rainfall import ROOT, run
from run_surface_routing import csv_steps


RAW = ROOT / "data" / "rainfall" / "raw" / "mosdac" / "3RIMG_L2B_IMC"
PROCESSED = ROOT / "data" / "rainfall" / "processed" / "mosdac" / "mosdac_bellandur.csv"
METADATA = ROOT / "data" / "rainfall" / "metadata" / "mosdac_bellandur.json"


@unittest.skipUnless(RAW.exists(), "local MOSDAC dataset is not present")
class MosdacRainfallTests(unittest.TestCase):
    def test_real_dataset_has_expected_count_and_readable_profiles(self):
        files = sorted(RAW.glob("*.tif"))
        self.assertEqual(len(files), 341)
        with rasterio.open(files[0]) as dataset:
            self.assertEqual((dataset.width, dataset.height, dataset.count), (28, 28, 1))
            self.assertEqual(str(dataset.crs), "EPSG:4326")
            self.assertEqual(dataset.nodata, -999.0)
            self.assertEqual(dataset.dtypes[0], "float32")
            self.assertGreaterEqual(float(dataset.read(1).max()), 0.0)

    def test_ingestion_metadata_and_p3_input_contract(self):
        metadata = run()
        self.assertEqual(metadata["raw_file_count"], 341)
        self.assertEqual(metadata["source_product"], "3RIMG_L2B_IMC")
        self.assertEqual(metadata["temporal_coverage"]["unique_timestamps"], 341)
        self.assertEqual(metadata["aoi_handling"]["pixels_per_timestamp"], 2)
        self.assertTrue(metadata["validation"]["all_files_cover_bbox"])
        self.assertTrue(metadata["model_input_compatibility"]["p3_surface_routing"])
        with PROCESSED.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 682)
        self.assertTrue({"timestamp", "latitude", "longitude", "rainfall_mm", "source"}.issubset(rows[0]))
        self.assertEqual(rows[0]["source"], "mosdac_insat3dr")
        self.assertEqual(rows[0]["source_product"], "3RIMG_L2B_IMC")
        self.assertTrue(METADATA.exists())
        self.assertEqual(json.loads(METADATA.read_text(encoding="utf-8"))["raw_file_count"], 341)

    def test_normalized_product_is_consumable_by_existing_p3_csv_interface(self):
        source, timestep, steps = csv_steps(
            PROCESSED,
            (3, 3),
            {"crs": "EPSG:4326", "transform": (0.01, 0.0, 77.65, 0.0, -0.01, 12.95)},
            1800,
        )
        self.assertEqual(source, "mosdac_insat3dr")
        self.assertEqual(timestep, 1800)
        self.assertEqual(len(steps), 341)
