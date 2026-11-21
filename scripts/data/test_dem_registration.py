import unittest

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject

import build_swmm_model as swmm
import process_dem as dem
from run_manifest import checksum
import run_surface_routing as surface


class DemRegistrationTests(unittest.TestCase):
    def test_boundary_postings_and_crop(self):
        r = dem.HGT_RESOLUTION_DEGREES
        bbox = {"min_lon": 77, "max_lon": 77 + r, "min_lat": 13 - r, "max_lat": 13}
        (rows, cols), edges = dem.aligned_window(bbox)
        self.assertEqual((rows.start, rows.stop, cols.start, cols.stop), (0, 2, 0, 2))
        transform = from_origin(edges["min_lon"], edges["max_lat"], r, r)
        self.assertTrue(np.allclose(transform * (0.5, 0.5), (77, 13), rtol=0, atol=1e-12))

    def test_native_source_and_crops_match_the_hgt_driver(self):
        if not dem.SOURCE_TIF.exists() or not dem.RAW_PATH.exists():
            self.skipTest("Local SRTM inputs unavailable")
        with rasterio.open("/vsigzip/" + dem.RAW_PATH.resolve().as_posix()) as raw:
            for path in (dem.SOURCE_TIF, dem.CLIPPED_TIF, dem.BUFFERED_TIF):
                with self.subTest(path=path.name), rasterio.open(path) as out:
                    self.assertEqual((out.crs, out.nodata, out.dtypes), (raw.crs, raw.nodata, raw.dtypes))
                    row, col = raw.index(*out.xy(0, 0))
                    np.testing.assert_allclose(out.xy(0, 0), raw.xy(row, col), rtol=0, atol=1e-12)
                    window = rasterio.windows.Window(col, row, out.width, out.height)
                    np.testing.assert_array_equal(out.read(1), raw.read(1, window=window))
                    np.testing.assert_array_equal(out.read_masks(1), raw.read_masks(1, window=window))

    def test_p5_and_p6_hydraulic_inputs_use_current_ground_elevations(self):
        nodes = {f["properties"]["node_id"]: f for f in swmm.load_json(swmm.NODES_PATH)["features"]}
        mapping = swmm.load_json(swmm.MAPPING_PATH)
        self.assertEqual(mapping["ground_elevation_dem_sha256"], checksum(dem.BUFFERED_TIF))
        offset = swmm.load_json(swmm.CONFIG_PATH)["model_assumptions"]["invert_offset_below_ground_m"]
        expected = {}
        with rasterio.open(dem.BUFFERED_TIF) as terrain:
            for row in mapping["node_mapping"]["mapped"]:
                xy = nodes[row["p4_id"]]["geometry"]["coordinates"][:2]
                ground = float(next(terrain.sample([xy], masked=True))[0])
                self.assertEqual(row["ground_elevation_m"], ground)
                expected[row["swmm_id"]] = ground - offset
        self.assertEqual(len(expected), 76)
        for path in [swmm.MODEL_PATH, swmm.ROOT / "data/coupling/input/bellandur_coupled_zero_rain.inp"]:
            inverts, drying, section = {}, [], ""
            for line in path.read_text().splitlines():
                fields = line.partition(";")[0].split()
                if not fields:
                    continue
                if fields[0].startswith("["):
                    section = fields[0]
                elif section in ("[JUNCTIONS]", "[OUTFALLS]"):
                    inverts[fields[0]] = float(fields[1])
                elif section == "[INFILTRATION]":
                    drying.append(float(fields[4]))
            self.assertEqual(inverts, expected)
            self.assertEqual(drying, [0.291667] * 81)

    def test_exported_surface_and_inundation_masks(self):
        root = swmm.ROOT / "data"
        rasters = sorted((root / "surface_routing/results").rglob("*.tif"))
        rasters += sorted((root / "coupling/results").rglob("*.tif"))
        inundation = sorted((root / "inundation/rasters").glob("*.tif"))
        self.assertTrue(rasters and inundation)
        with rasterio.open(surface.WORKING_DIR / "dem_working.tif") as terrain:
            terrain_mask = terrain.read_masks(1) > 0
            for path in rasters + inundation:
                with self.subTest(path=path), rasterio.open(path) as product:
                    self.assertEqual((product.crs, product.shape, product.transform),
                                     (terrain.crs, terrain.shape, terrain.transform))
                    valid = product.read_masks(1) > 0
                    if path in inundation:
                        self.assertTrue(np.any(valid))
                        self.assertFalse(np.any(valid & ~terrain_mask))
                    else:
                        np.testing.assert_array_equal(valid, terrain_mask)

    def test_derivatives_and_working_grid(self):
        projected = surface.WORKING_DIR / "dem_working.tif"
        if not projected.exists():
            self.skipTest("Working terrain assets unavailable")
        with rasterio.open(dem.BUFFERED_TIF) as native, rasterio.open(projected) as dst:
            self.assertEqual(dst.crs.to_epsg(), 32643)
            self.assertEqual(dst.dtypes[0], "float32")
            self.assertEqual(dst.nodata, native.nodata)
            expected = np.empty(dst.shape, dtype="float64")
            reproject(native.read(1), expected, src_transform=native.transform, src_crs=native.crs,
                      src_nodata=native.nodata, dst_transform=dst.transform, dst_crs=dst.crs,
                      dst_nodata=dst.nodata, resampling=Resampling.bilinear)
            actual = dst.read(1)
            np.testing.assert_array_equal(actual == dst.nodata, expected == dst.nodata)
            np.testing.assert_allclose(actual, expected, rtol=0, atol=0.0001)
            self.assertTrue(np.any(np.abs(actual - np.rint(actual)) > 0.1))
            for key, path in surface.P2_INPUTS.items():
                for source, reference in ((path, native), (surface.WORKING_DIR / f"{key}_working.tif", dst)):
                    with self.subTest(path=source.name), rasterio.open(source) as layer:
                        self.assertEqual((layer.crs, layer.shape, layer.transform),
                                         (reference.crs, reference.shape, reference.transform))
