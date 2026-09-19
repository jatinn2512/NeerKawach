"""Automated tests for the P3 routing core and generated working grid."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import rasterio

from surface_routing_core import RainfallStep, RoutingParameters, route_step, simulate


ROOT = Path(__file__).resolve().parents[2]


def steps(shape: tuple[int, int], values: list[float]) -> list[RainfallStep]:
    return [RainfallStep(f"2026-01-01T00:{index:02d}:00Z", np.full(shape, value / 1000.0)) for index, value in enumerate(values)]


def params(**overrides) -> RoutingParameters:
    values = {"timestep_seconds": 300, "runoff_coefficient": 1.0, "infiltration_rate_mm_per_hour": 0.0, "boundary_condition": "closed", "mass_balance_tolerance_m3": 1e-8}
    values.update(overrides)
    return RoutingParameters(**values)


class SurfaceRoutingTests(unittest.TestCase):
    def test_no_rain_generates_no_water(self):
        dem = np.zeros((2, 2), dtype=float)
        valid = np.ones_like(dem, dtype=bool)
        result = simulate(dem, valid, steps(dem.shape, [0.0, 0.0]), 900.0, params())
        self.assertEqual(result.total_rainfall_input_m3, 0.0)
        self.assertEqual(result.final_stored_water_m3, 0.0)
        self.assertTrue(np.all(result.final_depth_m == 0))

    def test_uniform_rain_mass_balance(self):
        dem = np.zeros((2, 2), dtype=float)
        valid = np.ones_like(dem, dtype=bool)
        result = simulate(dem, valid, steps(dem.shape, [10.0]), 900.0, params())
        self.assertAlmostEqual(result.total_rainfall_input_m3, 36.0)
        self.assertAlmostEqual(result.total_runoff_input_m3, 36.0)
        self.assertAlmostEqual(result.total_coefficient_loss_m3, 0.0)
        self.assertAlmostEqual(result.total_infiltration_loss_m3, 0.0)
        self.assertAlmostEqual(result.total_surface_water_input_m3, 36.0)
        self.assertAlmostEqual(result.final_stored_water_m3, 36.0)
        self.assertAlmostEqual(result.mass_balance_residual_m3, 0.0, places=10)
        self.assertAlmostEqual(result.surface_balance_residual_m3, 0.0, places=10)

    def test_water_moves_down_a_simple_slope(self):
        dem = np.array([[2.0, 1.0, 0.0]])
        valid = np.ones_like(dem, dtype=bool)
        initial = np.array([[0.1, 0.0, 0.0]])
        updated, outflow = route_step(dem, initial, valid, np.zeros_like(dem, dtype=np.int16), 900.0, params(), 30.0, 30.0)
        self.assertEqual(outflow, 0.0)
        self.assertGreater(updated[0, 1], 0.0)
        self.assertLess(updated[0, 0], initial[0, 0])
        self.assertTrue(np.all(updated >= 0))

    def test_bowl_accumulates_water(self):
        dem = np.array([[2.0, 2.0, 2.0], [2.0, 0.0, 2.0], [2.0, 2.0, 2.0]])
        valid = np.ones_like(dem, dtype=bool)
        result = simulate(dem, valid, steps(dem.shape, [1.0]), 900.0, params())
        self.assertGreater(result.final_depth_m[1, 1], result.final_depth_m[0, 0])

    def test_open_boundary_reports_outflow(self):
        dem = np.zeros((2, 2), dtype=float)
        valid = np.ones_like(dem, dtype=bool)
        result = simulate(dem, valid, steps(dem.shape, [0.0]), 900.0, params(initial_water_depth_m=0.1, boundary_condition="open", boundary_outflow_fraction=0.5))
        self.assertGreater(result.total_boundary_outflow_m3, 0.0)
        self.assertAlmostEqual(result.final_stored_water_m3, 180.0)
        self.assertAlmostEqual(result.mass_balance_residual_m3, 0.0, places=10)

    def test_mass_conservation_with_losses(self):
        dem = np.zeros((3, 3), dtype=float)
        valid = np.ones_like(dem, dtype=bool)
        result = simulate(dem, valid, steps(dem.shape, [12.0, 4.0]), 900.0, params(runoff_coefficient=0.8, infiltration_rate_mm_per_hour=1.0))
        self.assertAlmostEqual(result.total_rainfall_input_m3, result.total_runoff_input_m3 + result.total_coefficient_loss_m3, places=10)
        self.assertAlmostEqual(result.total_runoff_input_m3, result.total_surface_water_input_m3 + result.total_infiltration_loss_m3, places=10)
        self.assertAlmostEqual(result.total_modeled_losses_m3, result.total_coefficient_loss_m3 + result.total_infiltration_loss_m3, places=10)
        self.assertAlmostEqual(result.mass_balance_residual_m3, 0.0, places=10)
        self.assertAlmostEqual(result.surface_balance_residual_m3, 0.0, places=10)
        self.assertAlmostEqual(result.maximum_routing_balance_residual_m3, 0.0, places=10)
        self.assertGreater(result.total_modeled_losses_m3, 0.0)

    def test_depth_never_negative(self):
        dem = np.array([[3.0, 1.0, 0.0]])
        valid = np.ones_like(dem, dtype=bool)
        result = simulate(dem, valid, steps(dem.shape, [20.0, 0.0, 0.0]), 900.0, params(d8_preference_factor=4.0))
        self.assertTrue(all(np.all(state["water_depth_m"] >= 0) for state in result.states))

    def test_deterministic_results(self):
        dem = np.array([[2.0, 1.0, 0.0]])
        valid = np.ones_like(dem, dtype=bool)
        first = simulate(dem, valid, steps(dem.shape, [3.0, 5.0, 1.0]), 900.0, params())
        second = simulate(dem, valid, steps(dem.shape, [3.0, 5.0, 1.0]), 900.0, params())
        np.testing.assert_array_equal(first.final_depth_m, second.final_depth_m)
        self.assertEqual(first.mass_balance_residual_m3, second.mass_balance_residual_m3)

    def test_projected_rasters_share_grid(self):
        paths = list((ROOT / "data" / "surface_routing" / "input").glob("*_working.tif"))
        if not paths:
            self.skipTest("run_surface_routing.py has not prepared projected inputs yet")
        with rasterio.open(paths[0]) as reference:
            for path in paths[1:]:
                with rasterio.open(path) as dataset:
                    self.assertEqual(dataset.crs, reference.crs)
                    self.assertEqual((dataset.width, dataset.height), (reference.width, reference.height))
                    self.assertEqual(dataset.transform, reference.transform)


if __name__ == "__main__":
    unittest.main()
