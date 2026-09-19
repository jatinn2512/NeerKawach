"""Pure NumPy surface-water routing primitives for the P3 prototype.

The model is intentionally small and conservative: rainfall becomes effective
surface input after explicit runoff/loss accounting, then water exchanges
between neighbouring cells according to the current water-surface head. The
DEM-derived D8 direction is only a preference factor, never a permanent route.
"""

from __future__ import annotations

from dataclasses import dataclass
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


def _preference(direction: np.ndarray | None, row: int, col: int, dr: int, dc: int, factor: float) -> float:
    if direction is None:
        return 1.0
    return factor if int(direction[row, col]) == D8_CODES.get((dr, dc), -1) else 1.0


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
    rows, cols = dem.shape
    transfers: list[tuple[int, int, int, int, float]] = []
    outgoing = np.zeros((rows, cols), dtype=np.float64)
    exchange_fraction = min(0.5, params.timestep_seconds / params.routing_timescale_seconds)
    head = dem + depth
    for dr, dc in PAIR_DIRECTIONS:
        distance = float(np.hypot(dc * dx_m, dr * dy_m))
        for row in range(max(0, -dr), min(rows, rows - dr)):
            for col in range(max(0, -dc), min(cols, cols - dc)):
                nr, nc = row + dr, col + dc
                if not valid[row, col] or not valid[nr, nc]:
                    continue
                difference = float(head[row, col] - head[nr, nc])
                if difference > 0:
                    sr, sc, tr, tc = row, col, nr, nc
                    pref = _preference(direction, sr, sc, dr, dc, params.d8_preference_factor)
                elif difference < 0:
                    sr, sc, tr, tc = nr, nc, row, col
                    pref = _preference(direction, sr, sc, -dr, -dc, params.d8_preference_factor)
                    difference = -difference
                else:
                    continue
                # Head difference [m] × cell area [m²] gives a volume. The
                # exchange fraction is the explicit stability limiter.
                volume = difference * cell_area_m2 * exchange_fraction * pref
                source_volume = float(depth[sr, sc] * cell_area_m2)
                volume = min(volume, source_volume)
                if volume > 0:
                    transfers.append((sr, sc, tr, tc, volume))
                    outgoing[sr, sc] += volume

    scale = np.ones((rows, cols), dtype=np.float64)
    available = depth * cell_area_m2
    over = outgoing > available
    scale[over] = available[over] / outgoing[over]
    delta_volume = np.zeros((rows, cols), dtype=np.float64)
    for sr, sc, tr, tc, volume in transfers:
        moved = volume * scale[sr, sc]
        delta_volume[sr, sc] -= moved
        delta_volume[tr, tc] += moved
    result = depth + delta_volume / cell_area_m2
    result[~valid] = 0.0
    result[result < 0] = 0.0
    return result


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
    max_depth = depth.copy()
    max_value = float(np.max(max_depth[valid])) if np.any(valid) else 0.0
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
        effective_runoff = rainfall * params.runoff_coefficient
        coefficient_loss = rainfall - effective_runoff
        infiltration = np.minimum(effective_runoff, infiltration_limit_m)
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
        if step_max > max_value:
            max_value = step_max
            max_depth = depth.copy()
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
