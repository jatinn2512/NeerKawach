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
    def dry_steps(self, bed, initial, count, timestep=300, valid=None, direction=None):
        valid = np.ones(bed.shape, dtype=bool) if valid is None else valid
        water = initial.copy()
        storage = np.sum(initial[valid]) * 900
        history = [water.copy()]
        for _ in range(count):
            water, outflow = route_step(bed, water, valid, direction, 900.0,
                                        params(timestep_seconds=timestep), 30, 30)
            self.assertEqual(outflow, 0.0)
            self.assertTrue(np.all(water >= 0))
            self.assertTrue(np.all(water[~valid] == 0))
            np.testing.assert_allclose(water.sum() * 900, storage, rtol=2e-14, atol=0)
            history.append(water.copy())
        return np.array(history)

    def test_constant_head_and_disconnected_dry_cells(self):
        flat = np.zeros((3, 3))
        uniform = np.full_like(flat, 0.1)
        np.testing.assert_array_equal(self.dry_steps(flat, uniform, 4)[-1], uniform)
        bed = np.array([[2., 1., 0., np.nan, 0.], [2., 0., 1., np.nan, 0.]])
        valid = np.isfinite(bed)
        water = np.array([[0., 1., 2., 0., 0.], [0., 2., 1., 0., 0.]])
        history = self.dry_steps(bed, water, 8, valid=valid)
        np.testing.assert_array_equal(history[-1], water)

    def test_isolated_wet_cell_and_shallow_film(self):
        bed = np.full((3, 3), 880.)
        for amount in [1., 1e-15]:
            with self.subTest(amount=amount):
                initial = np.zeros_like(bed)
                initial[1, 1] = amount
                history = self.dry_steps(bed, initial, 32)
                self.assertTrue(np.all(history[1] > 0))
                peaks = np.max(history, axis=(1, 2))
                self.assertTrue(np.all(np.diff(peaks) <= amount * 1e-14))
                np.testing.assert_allclose(history[-1], amount / 9, rtol=1e-12, atol=0)

    def test_multiple_donors_fill_flat_receiver_without_overshoot(self):
        bed = np.zeros((3, 3))
        initial = np.ones_like(bed)
        initial[1, 1] = 0
        history = self.dry_steps(bed, initial, 32)
        centre = history[:, 1, 1]
        self.assertGreater(centre[1], 0)
        self.assertTrue(np.all(np.diff(centre) >= -1e-14))
        self.assertTrue(np.all(centre <= 8 / 9 + 1e-14))
        np.testing.assert_allclose(history[-1], 8 / 9, atol=1e-12)

    def test_basin_recedes_to_hydrostatic_depth(self):
        bed = np.array([[3., 1., 0., 1., 3.]])
        initial = np.array([[1., 0., 4., 0., 0.]])
        history = self.dry_steps(bed, initial, 50)
        # Five depth-metres on three inundated cells gives stage (5+2)/3.
        expected = np.maximum(7 / 3 - bed, 0)
        np.testing.assert_allclose(history[-1], expected, atol=1e-10, rtol=0)
        energy = np.sum(bed * history + history**2 / 2, axis=(1, 2))
        self.assertTrue(np.all(np.diff(energy) <= 1e-13))
        self.assertEqual(history[-1, 0, 4], 0)

    def test_axial_distance_and_d8_weight_on_first_transfer(self):
        bed = np.zeros((3, 3))
        initial = np.zeros_like(bed)
        initial[1, 1] = 1
        direction = np.zeros(bed.shape, dtype=np.int16)
        direction[1, 1] = 1  # east
        after = self.dry_steps(bed, initial, 1, timestep=10, direction=direction)[1]
        self.assertAlmostEqual(after[1, 2], 1.25 * after[1, 0])
        self.assertAlmostEqual(after[1, 0], 2 * after[0, 0])
        self.assertGreater(after[0, 0], 0)

    def test_refinement_toward_exact_two_cell_recession(self):
        bed, initial = np.zeros((1, 2)), np.array([[1., 0.]])
        exact_difference = np.exp(-2 * 300 / 600)
        errors = []
        for dt in (300, 150, 75, 37.5):
            history = self.dry_steps(bed, initial, int(300 / dt), timestep=dt)
            difference = history[:, 0, 0] - history[:, 0, 1]
            self.assertTrue(np.all(difference >= 0))
            self.assertTrue(np.all(np.diff(difference) <= 0))
            errors.append(abs(difference[-1] - exact_difference))
        self.assertTrue(np.all(np.diff(errors) < 0))

    def test_cellwise_peaks_and_first_peak_timestamp(self):
        bed = np.array([[2., 0., 2.]])
        pulses = [RainfallStep(str(i), rain) for i, rain in enumerate(
            [np.array([[3., 0., 0.]]), np.array([[0., 0., 2.]]), np.zeros_like(bed)])]
        result = simulate(bed, np.ones_like(bed, dtype=bool), pulses, 900., params(timestep_seconds=30))
        frames = np.stack([s["water_depth_m"] for s in result.states])
        peak_index = int(np.argmax(frames.max(axis=(1, 2))))
        np.testing.assert_array_equal(result.maximum_depth_m, frames.max(axis=0))
        self.assertFalse(np.array_equal(result.maximum_depth_m, frames[peak_index]))
        self.assertEqual((result.maximum_depth_index, result.maximum_depth_timestamp), (peak_index, str(peak_index)))
        self.assertEqual(result.maximum_depth_value_m, frames.max())

    def test_no_rain_generates_no_water(self):
        dem = np.zeros((2, 2), dtype=float)
        valid = np.ones_like(dem, dtype=bool)
        result = simulate(dem, valid, steps(dem.shape, [0.0, 0.0]), 900.0, params())
        self.assertEqual(result.total_rainfall_input_m3, 0.0)
        self.assertEqual(result.final_stored_water_m3, 0.0)
        self.assertTrue(np.all(result.final_depth_m == 0))
        self.assertEqual(result.maximum_depth_index, 0)

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
        # Internal hydraulic substeps may carry the pulse past the middle cell.
        self.assertGreater(updated[0, 1:].sum(), 0.0)
        self.assertLess(updated[0, 0], initial[0, 0])
        self.assertAlmostEqual(updated.sum(), initial.sum())
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
