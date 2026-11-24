"""Pure NumPy surface-water routing primitives for the P3 prototype.

The model is intentionally small and conservative: rainfall becomes effective
surface input after explicit runoff/loss accounting, then water exchanges
between neighbouring cells according to the current water-surface head. The
DEM-derived D8 direction is only a preference factor, never a permanent route.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class RainfallStep:
    timestamp: str
    rainfall_depth_m: np.ndarray


@dataclass(frozen=True)
class RoutingParameters:
    timestep_seconds: float = 300.0
    runoff_coefficient: float = 0.75
    infiltration_rate_mm_per_hour: float = 0.5
    initial_water_depth_m: float = 0.0
    routing_timescale_seconds: float = 600.0
    d8_preference_factor: float = 1.25
    boundary_condition: str = "closed"
    boundary_outflow_fraction: float = 0.25
    mass_balance_tolerance_m3: float = 1e-6

    def validate(self) -> None:
        if self.timestep_seconds <= 0 or self.routing_timescale_seconds <= 0:
            raise ValueError("timestep and routing timescale must be positive")
        if not 0 <= self.runoff_coefficient <= 1:
            raise ValueError("runoff coefficient must be between 0 and 1")
        if self.infiltration_rate_mm_per_hour < 0 or self.initial_water_depth_m < 0:
            raise ValueError("infiltration and initial depth must be non-negative")
        if self.d8_preference_factor < 1:
            raise ValueError("D8 preference factor must be at least 1")
        if self.boundary_condition not in {"closed", "open"}:
            raise ValueError("boundary condition must be 'closed' or 'open'")
        if not 0 <= self.boundary_outflow_fraction <= 1:
            raise ValueError("boundary outflow fraction must be between 0 and 1")
        if self.mass_balance_tolerance_m3 <= 0:
            raise ValueError("mass-balance tolerance must be positive")


class MassBalanceError(RuntimeError):
    """Raised when conservative accounting exceeds the configured tolerance."""


@dataclass
class SimulationResult:
    states: list[dict]
    initial_stored_water_m3: float
    total_rainfall_input_m3: float
    total_runoff_input_m3: float
    total_coefficient_loss_m3: float
    total_infiltration_loss_m3: float
    total_surface_water_input_m3: float
    total_modeled_losses_m3: float
    total_boundary_outflow_m3: float
    final_stored_water_m3: float
    mass_balance_residual_m3: float
    surface_balance_residual_m3: float
    maximum_routing_balance_residual_m3: float
    final_depth_m: np.ndarray
    maximum_depth_m: np.ndarray
    maximum_depth_value_m: float
    maximum_depth_index: int | None
    maximum_depth_timestamp: str | None


# Unique undirected neighbour pairs: E, SE, S and SW. The reverse direction
# is selected from current surface head for each pair at every time step.
PAIR_DIRECTIONS = ((0, 1), (1, 1), (1, 0), (1, -1))
D8_CODES = {(-1, 0): 64, (-1, 1): 128, (0, 1): 1, (1, 1): 2, (1, 0): 4, (1, -1): 8, (0, -1): 16, (-1, -1): 32}


def _check_arrays(dem: np.ndarray, valid: np.ndarray, direction: np.ndarray | None, depth: np.ndarray) -> None:
    if dem.shape != valid.shape or dem.shape != depth.shape:
        raise ValueError("DEM, valid mask and water depth arrays must have the same shape")
    if direction is not None and direction.shape != dem.shape:
        raise ValueError("Flow-direction raster must align with DEM")
    if np.any(~np.isfinite(dem[valid])) or np.any(~np.isfinite(depth)):
        raise ValueError("DEM/depth arrays contain non-finite values")
    if np.any(depth[valid] < -1e-12):
        raise ValueError("Water depth cannot be negative")


def _redistribute(
    dem: np.ndarray,
    depth: np.ndarray,
    valid: np.ndarray,
    direction: np.ndarray | None,
    cell_area_m2: float,
    params: RoutingParameters,
    dx_m: float,
    dy_m: float,
) -> np.ndarray:
    """Integrate head-driven exchange on equal-area cells over one forcing step."""
    if not (dx_m > 0 and dy_m > 0 and cell_area_m2 > 0):
        raise ValueError("Cell dimensions and area must be positive")
    rows, cols = dem.shape
    cells = np.arange(dem.size).reshape(dem.shape)
    endpoints_a, endpoints_b = [], []
    weights_ab, weights_ba = [], []
    for dr, dc in PAIR_DIRECTIONS:
        left = cells[:rows-dr, max(0, -dc):min(cols, cols-dc)]
        right = cells[dr:, max(0, dc):min(cols, cols+dc)]
        connected = valid.flat[left] & valid.flat[right]
        a, b = left[connected], right[connected]
        endpoints_a.append(a)
        endpoints_b.append(b)
        weight = cell_area_m2 / ((dc * dx_m)**2 + (dr * dy_m)**2)
        forward = np.full(a.size, weight)
        reverse = np.full(b.size, weight)
        if direction is not None:
            forward[direction.flat[a] == D8_CODES[dr, dc]] *= params.d8_preference_factor
            reverse[direction.flat[b] == D8_CODES[-dr, -dc]] *= params.d8_preference_factor
        weights_ab.append(forward)
        weights_ba.append(reverse)

    a, b = np.concatenate(endpoints_a), np.concatenate(endpoints_b)
    forward, reverse = np.concatenate(weights_ab), np.concatenate(weights_ba)
    bed = np.asarray(dem, dtype=np.float64).ravel()
    bed_drop = bed[a] - bed[b]
    water = np.where(valid, depth, 0.0).astype(np.float64).ravel()

    # Bound the sum of *all* incident coefficients at either end by 1/2.
    # Each substep then retains at least half the local head in the convex
    # combination. The bound holds for either possible donor on every edge.
    largest_weight = np.maximum(forward, reverse)
    degree = (np.bincount(a, weights=largest_weight, minlength=water.size)
              + np.bincount(b, weights=largest_weight, minlength=water.size))
    interval = params.timestep_seconds / params.routing_timescale_seconds
    substeps = max(1, ceil(2 * interval * degree.max(initial=0.0)))
    for _ in range(substeps):
        head_drop = bed_drop + (water[a] - water[b])
        downhill = head_drop >= 0
        donor = np.where(downhill, a, b)
        receiver = np.where(downhill, b, a)
        requested = (interval / substeps) * np.where(downhill, forward, reverse) * np.abs(head_drop)
        outgoing = np.bincount(donor, weights=requested, minlength=water.size)
        sent = np.minimum(water, outgoing)
        # On equal-area cells, the same transferred depth represents the same
        # volume at both ends. Keep the donor's unspent water exactly nonnegative.
        fraction = np.divide(sent, outgoing, out=np.zeros_like(water), where=outgoing > 0)
        incoming = np.bincount(receiver, weights=requested * fraction[donor], minlength=water.size)
        water = (water - sent) + incoming
    return water.reshape(dem.shape)


def _apply_boundary(depth: np.ndarray, valid: np.ndarray, cell_area_m2: float, params: RoutingParameters) -> tuple[np.ndarray, float]:
    if params.boundary_condition == "closed":
        return depth, 0.0
    boundary = np.zeros_like(valid, dtype=bool)
    boundary[0, :] = True
    boundary[-1, :] = True
    boundary[:, 0] = True
    boundary[:, -1] = True
    boundary &= valid
    volume = float(np.sum(depth[boundary] * cell_area_m2 * params.boundary_outflow_fraction))
    updated = depth.copy()
    updated[boundary] *= 1.0 - params.boundary_outflow_fraction
    return updated, volume


def route_step(
    dem: np.ndarray,
    depth: np.ndarray,
    valid: np.ndarray,
    direction: np.ndarray | None,
    cell_area_m2: float,
    params: RoutingParameters,
    dx_m: float,
    dy_m: float,
) -> tuple[np.ndarray, float]:
    """Redistribute current water and apply the configured boundary condition."""
    _check_arrays(dem, valid, direction, depth)
    moved = _redistribute(dem, depth, valid, direction, cell_area_m2, params, dx_m, dy_m)
    bounded, boundary_outflow = _apply_boundary(moved, valid, cell_area_m2, params)
    bounded[~valid] = 0.0
    if np.any(bounded[valid] < -1e-12):
        raise RuntimeError("Routing produced negative water depth")
    return np.maximum(bounded, 0.0), boundary_outflow


def simulate(
    dem: np.ndarray,
    valid: np.ndarray,
    rainfall_steps: Iterable[RainfallStep],
    cell_area_m2: float,
    params: RoutingParameters,
    direction: np.ndarray | None = None,
    dx_m: float = 30.0,
    dy_m: float = 30.0,
    spatial_runoff=None,
) -> SimulationResult:
    """Run a deterministic conservative time-stepped surface-water simulation."""
    params.validate()
    if cell_area_m2 <= 0 or dx_m <= 0 or dy_m <= 0:
        raise ValueError("cell area and pixel dimensions must be positive")
    depth = np.full(dem.shape, params.initial_water_depth_m, dtype=np.float64)
    depth[~valid] = 0.0
    _check_arrays(dem, valid, direction, depth)
    initial_volume = float(np.sum(depth[valid] * cell_area_m2))
    total_rainfall = 0.0
    total_runoff = 0.0
    total_coefficient_loss = 0.0
    total_infiltration_loss = 0.0
    total_surface_input = 0.0
    total_boundary = 0.0
    maximum_routing_residual = 0.0
    states: list[dict] = []
    # Products summarize the saved step-end states, including the first dry frame.
    max_depth = np.zeros_like(depth)
    max_value = 0.0
    max_index: int | None = None
    max_timestamp: str | None = None
    infiltration_limit_m = params.infiltration_rate_mm_per_hour / 1000.0 * params.timestep_seconds / 3600.0

    for index, step in enumerate(rainfall_steps):
        rainfall = np.asarray(step.rainfall_depth_m, dtype=np.float64)
        if rainfall.shape != dem.shape:
            raise ValueError("Rainfall forcing grid is not aligned with the DEM")
        if np.any(~np.isfinite(rainfall)) or np.any(rainfall[valid] < 0):
            raise ValueError("Rainfall forcing must be finite and non-negative")
        rainfall = rainfall.copy()
        rainfall[~valid] = 0.0
        rainfall_volume = float(np.sum(rainfall * cell_area_m2))
        effective_runoff = rainfall if spatial_runoff is not None else rainfall * params.runoff_coefficient
        coefficient_loss = rainfall - effective_runoff
        infiltration = (spatial_runoff.infiltration(rainfall, params.timestep_seconds)
                        if spatial_runoff is not None else np.minimum(effective_runoff, infiltration_limit_m))
        surface_input = effective_runoff - infiltration
        depth += surface_input
        depth[~valid] = 0.0
        infiltration_volume = float(np.sum(infiltration * cell_area_m2))
        coefficient_loss_volume = float(np.sum(coefficient_loss * cell_area_m2))
        surface_input_volume = float(np.sum(surface_input * cell_area_m2))
        losses = infiltration_volume + coefficient_loss_volume
        pre_route_volume = float(np.sum(depth[valid] * cell_area_m2))
        depth, boundary_outflow = route_step(dem, depth, valid, direction, cell_area_m2, params, dx_m, dy_m)
        stored_volume = float(np.sum(depth[valid] * cell_area_m2))
        routing_residual = pre_route_volume - boundary_outflow - stored_volume
        maximum_routing_residual = max(maximum_routing_residual, abs(routing_residual))
        if abs(routing_residual) > params.mass_balance_tolerance_m3:
            raise MassBalanceError(f"Routing residual {routing_residual} m3 exceeds tolerance {params.mass_balance_tolerance_m3} m3 at step {index}")
        total_rainfall += rainfall_volume
        total_runoff += float(np.sum(effective_runoff * cell_area_m2))
        total_coefficient_loss += coefficient_loss_volume
        total_infiltration_loss += infiltration_volume
        total_surface_input += surface_input_volume
        total_boundary += boundary_outflow
        residual = initial_volume + total_rainfall - total_coefficient_loss - total_infiltration_loss - total_boundary - stored_volume
        surface_residual = initial_volume + total_surface_input - total_boundary - stored_volume
        if abs(residual) > params.mass_balance_tolerance_m3:
            raise MassBalanceError(f"Mass-balance residual {residual} m3 exceeds tolerance {params.mass_balance_tolerance_m3} m3 at step {index}")
        if abs(surface_residual) > params.mass_balance_tolerance_m3:
            raise MassBalanceError(f"Surface-input balance residual {surface_residual} m3 exceeds tolerance {params.mass_balance_tolerance_m3} m3 at step {index}")
        step_max = float(np.max(depth[valid])) if np.any(valid) else 0.0
        np.maximum(max_depth, depth, out=max_depth)
        if max_index is None or step_max > max_value:
            max_value = step_max
            max_index = index
            max_timestamp = step.timestamp
        states.append({
            "index": index,
            "timestamp": step.timestamp,
            "rainfall_input_m3": rainfall_volume,
            "runoff_input_m3": float(np.sum(effective_runoff * cell_area_m2)),
            "coefficient_loss_m3": coefficient_loss_volume,
            "infiltration_loss_m3": infiltration_volume,
            "surface_water_input_m3": surface_input_volume,
            "modeled_losses_m3": losses,
            "boundary_outflow_m3": boundary_outflow,
            "stored_surface_water_m3": stored_volume,
            "mass_balance_residual_m3": residual,
            "surface_balance_residual_m3": surface_residual,
            "routing_balance_residual_m3": routing_residual,
            "water_depth_m": depth.copy(),
        })
    final_volume = float(np.sum(depth[valid] * cell_area_m2))
    total_losses = total_coefficient_loss + total_infiltration_loss
    residual = initial_volume + total_rainfall - total_losses - total_boundary - final_volume
    surface_residual = initial_volume + total_surface_input - total_boundary - final_volume
    return SimulationResult(
        states=states,
        initial_stored_water_m3=initial_volume,
        total_rainfall_input_m3=total_rainfall,
        total_runoff_input_m3=total_runoff,
        total_coefficient_loss_m3=total_coefficient_loss,
        total_infiltration_loss_m3=total_infiltration_loss,
        total_surface_water_input_m3=total_surface_input,
        total_modeled_losses_m3=total_losses,
        total_boundary_outflow_m3=total_boundary,
        final_stored_water_m3=final_volume,
        mass_balance_residual_m3=residual,
        surface_balance_residual_m3=surface_residual,
        maximum_routing_balance_residual_m3=maximum_routing_residual,
        final_depth_m=depth,
        maximum_depth_m=max_depth,
        maximum_depth_value_m=max_value,
        maximum_depth_index=max_index,
        maximum_depth_timestamp=max_timestamp,
    )
