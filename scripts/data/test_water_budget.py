import unittest

import numpy as np
from build_swmm_model import MODEL_PATH, STORM_PATH, hours_to_days, load_json
from surface_routing_core import RainfallStep, RoutingParameters, simulate
from water_budget import budget, exchange_budget, funded_rate, settle_inlet, surface_budgets


class WaterBudgetTests(unittest.TestCase):
    def test_horton(self):
        for hours, days in ((0, 0), (6, .25), (7, 7/24), (24, 1), (48, 2)):
            self.assertEqual(hours_to_days(hours), days)

    def test_generated_horton_and_intensity_encode_the_fixture(self):
        if not MODEL_PATH.is_file():
            self.skipTest("Generated P5 INP is unavailable")
        storm = load_json(STORM_PATH)
        section = ""
        drying_times, depths = [], []
        for line in MODEL_PATH.read_text(encoding="utf-8").splitlines():
            fields = line.partition(";")[0].split()
            if not fields:
                continue
            if fields[0].startswith("["):
                section = fields[0]
            elif section == "[INFILTRATION]":
                drying_times.append(float(fields[4]))
            elif section == "[TIMESERIES]" and fields[0] == "SyntheticStorm":
                depths.append(float(fields[3]) * storm["timestep_seconds"] / 3600)
        self.assertTrue(drying_times)
        self.assertTrue(all(abs(value - 7/24) < 1e-5 for value in drying_times))
        np.testing.assert_allclose(depths, [row["rainfall_mm"] for row in storm["records"]])

    def test_rate_volume_and_accumulation(self):
        # 12 mm/h over a quarter hour is 3 mm, or 0.3 m³ over 100 m².
        # Feed P3 interval depths. The same conversion inverted is used by the P5 rain gage.
        dem = np.zeros((1, 1))
        dt = 900
        steps = [RainfallStep(t, np.full((1, 1), 12 * dt / 3600 / 1000)) for t in ("t1", "t2")]
        params = RoutingParameters(timestep_seconds=dt, runoff_coefficient=1, infiltration_rate_mm_per_hour=0,
                                   boundary_condition="closed")
        result = simulate(dem, np.ones((1, 1), dtype=bool), steps, 100, params)
        ledger = surface_budgets(result.states, 0)
        self.assertAlmostEqual(ledger[0]["step"]["storage_change_m3"], .3)
        self.assertAlmostEqual(ledger[-1]["cumulative"]["input_m3"], .6)
        self.assertAlmostEqual(ledger[-1]["cumulative"]["residual_m3"], 0)

    def test_exchange_counts_once(self):
        # 10 rain, 4 captured, 1 returned. Surface stores 7. Drain stores 2 and discharges 1.
        step = dict(timestamp="t", rainfall_input_m3=10, coefficient_loss_m3=0, infiltration_loss_m3=0,
                    boundary_outflow_m3=0, surface_to_drainage_m3=4, overflow_return_m3=1,
                    stored_surface_water_m3=7)
        self.assertEqual(surface_budgets([step], 0)[0]["step"]["residual_m3"], 0)
        self.assertEqual(exchange_budget(4, 4, 1, 1, 0)["capture"]["residual_m3"], 0)
        self.assertEqual(budget(10, 1, 0, 7+2)["residual_m3"], 0)
        error = exchange_budget(4, 3.5, 1, 0.75, 0)
        self.assertEqual(error["capture"]["residual_m3"], 0.5)
        self.assertEqual(error["overflow"]["residual_m3"], 0.25)
        self.assertEqual(budget(10, 1, 0, 8)["residual_percent_of_input"], 10)

    def test_rate_reserves_both_halves_of_a_native_transition(self):
        for offered, available, previous in [(75, 75, 0), (15, 20, .25), (0, 3.75, .25), (0, 0, 0)]:
            q = funded_rate(offered, available, previous, 300, 30)
            self.assertLessEqual(q * 300, offered + 1e-9)
            for first_step in (.001, 10, 30):
                debit = q * 300 + (previous - q) * first_step / 2
                self.assertLessEqual(debit + q * 15, available + 1e-9)
        with self.assertRaises(ValueError):
            funded_rate(0, 0, .25, 300, 30)

    def test_shared_inlet_debits_only_its_contributing_cells(self):
        balances = {"a": 1.5, "b": 4.5, "other": 12}
        settle_inlet(balances, ["a", "b"], 2)
        self.assertAlmostEqual(balances["a"], 1)
        self.assertAlmostEqual(balances["b"], 3)
        self.assertEqual(balances["other"], 12)
        with self.assertRaises(ValueError):
            settle_inlet(balances, ["a", "b"], 4.1)
        with self.assertRaises(ValueError):
            settle_inlet(balances, [], 1)
        settle_inlet(balances, [], 0)

    def test_zero_flow_and_storage_release(self):
        self.assertIsNone(budget(0, 0, 0, 0)["residual_percent_of_input"])
        self.assertEqual(budget(0, 2, 3, 1)["residual_m3"], 0)
