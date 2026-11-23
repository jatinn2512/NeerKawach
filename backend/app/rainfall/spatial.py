"""Native-footprint rainfall mapping on a north-up, metre-based DEM grid."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.warp import transform, transform_bounds

from .contracts import RainfallRecord

EDGE_STEP_DEG = 0.00025
AREA_ATOL = 1e-6  # square metres, used only for numerical comparisons
INTEGRAL_ATOL = 1e-7  # m³ for depth, m³/h for rate
RTOL = 1e-11
MOSDAC = "mosdac_insat3dr"
IMD = "imd_ncmrwf_gpm_merged_daily"
INELIGIBLE = {
    "arg_aws": "Station point observations have no areal support.",
    "open_meteo_precipitation_forecast": "The returned point has no documented native footprint.",
    "rainviewer_radar_observations": "Visualization references have no quantitative rain measurement.",
    "imerg": "No local NASA IMERG observations are available.",
}


@dataclass(frozen=True)
class WorkingGrid:
    crs: CRS
    affine: Affine
    valid: np.ndarray

    def __post_init__(self):
        a = self.affine
        if not self.crs.is_projected or self.crs.linear_units_factor[1] != 1:
            raise ValueError("target CRS must be projected in metres")
        if a.a <= 0 or a.e >= 0 or a.b or a.d or not np.isfinite(tuple(a)).all():
            raise ValueError("expected a north-up target affine")
        if self.valid.ndim != 2 or self.valid.dtype != bool or not self.valid.any():
            raise ValueError("expected a nonempty DEM validity mask")

    @classmethod
    def read(cls, dem: Path, metadata: Path) -> WorkingGrid:
        declared = json.loads(metadata.read_text(encoding="utf-8"))["working_grid"]
        with rasterio.open(dem) as ds:
            if (ds.crs != CRS.from_user_input(declared["crs"])
                    or ds.shape != (declared["height"], declared["width"])
                    or not np.allclose(tuple(ds.transform)[:6], declared["transform"][:6], atol=1e-8, rtol=0)):
                raise ValueError("DEM alignment disagrees with working-grid metadata")
            terrain = ds.read(1, masked=True)
            grid = cls(ds.crs, ds.transform, ~np.ma.getmaskarray(terrain) & np.isfinite(terrain.data))
        if not math.isclose(grid.cell_area, declared["cell_area_m2"], abs_tol=1e-8, rel_tol=0):
            raise ValueError("DEM cell area disagrees with working-grid metadata")
        return grid

    @property
    def cell_area(self):
        return -self.affine.a * self.affine.e

    def geographic_bbox(self):
        height, width = self.valid.shape
        bounds = rasterio.transform.array_bounds(height, width, self.affine)
        west, south, east, north = transform_bounds(self.crs, "EPSG:4326", *bounds, densify_pts=101)
        return dict(min_lon=west, min_lat=south, max_lon=east, max_lat=north)


def pixel_key(record: RainfallRecord):
    g = record.geometry or {}
    if record.source not in (MOSDAC, IMD):
        raise ValueError(INELIGIBLE.get(record.source, "unsupported gridded rainfall source"))
    if g.get("kind") != "grid_cell" or not g.get("footprint") or not g.get("crs"):
        raise ValueError("native grid-cell footprint and CRS required")
    return g["row"], g["column"]


def layout_key(records):
    """Stable across frame ordering, rainfall values and validity changes."""
    return tuple(sorted((r.source, pixel_key(r), r.geometry["crs"], tuple(r.geometry["footprint"]))
                        for r in records))


def projected_ring(bounds, source_crs, grid, step_deg=EDGE_STEP_DEG):
    """Transform geographic parallels/meridians, returning local target pixel coordinates."""
    west, south, east, north = bounds
    if not (np.isfinite(bounds).all() and west < east and south < north):
        raise ValueError("invalid native pixel bounds")
    source = CRS.from_user_input(source_crs)
    corners = [(west, south), (east, south), (east, north), (west, north)]
    if source == grid.crs:
        xs, ys = zip(*corners)
    else:
        if not source.is_geographic:
            raise ValueError("source must be geographic or already in the target CRS")
        ring = []
        for (x, y), (u, v) in zip(corners, corners[1:] + corners[:1]):
            count = max(1, math.ceil(max(abs(u-x), abs(v-y)) / step_deg))
            ring.extend((x + (u-x)*i/count, y + (v-y)*i/count) for i in range(count))
        xs, ys = transform(source, grid.crs, *zip(*ring))
    a = grid.affine
    projected = [((x-a.c)/a.a, (y-a.f)/a.e) for x, y in zip(xs, ys)]
    if not np.isfinite(projected).all():
        raise ValueError("footprint projection produced nonfinite coordinates")
    return projected


def _clip(ring, axis, bound, keep_above):
    """Sutherland–Hodgman clipping against one target-cell edge."""
    output = []
    if ring:
        p = ring[-1]
        inside = (p[axis] >= bound) if keep_above else (p[axis] <= bound)
        for q in ring:
            next_inside = (q[axis] >= bound) if keep_above else (q[axis] <= bound)
            if inside != next_inside:
                t = (bound-p[axis]) / (q[axis]-p[axis])
                other = p[1-axis] + t*(q[1-axis]-p[1-axis])
                output.append((bound, other) if axis == 0 else (other, bound))
            if next_inside:
                output.append(q)
            p, inside = q, next_inside
    return output


def _cell_areas(ring, grid):
    height, width = grid.valid.shape
    areas = np.zeros((height, width), dtype=np.float64)
    ring = _clip(_clip(ring, 0, 0, True), 0, width, False)
    for row in range(height):
        strip = _clip(_clip(ring, 1, row, True), 1, row+1, False)
        if len(strip) < 3:
            continue
        left = max(0, math.floor(min(p[0] for p in strip)))
        right = min(width, math.ceil(max(p[0] for p in strip)))
        for col in range(left, right):
            if not grid.valid[row, col]:
                continue
            polygon = _clip(_clip(strip, 0, col, True), 0, col+1, False)
            # Translate to the cell origin before applying the shoelace formula.
            local = [(x-col, y-row) for x, y in polygon]
            twice_area = math.fsum(x*v-y*u for (x,y), (u,v) in zip(local, local[1:]+local[:1]))
            areas[row, col] = abs(twice_area)*0.5*grid.cell_area
    return areas


def _domain_area(ring, grid):
    """Independent Green's-theorem integral against contiguous valid runs in each DEM row.

    Within a row's y strip, integrate clamp(x-left, 0, width) dy along each
    source boundary edge. The x derivative is one inside the run, zero outside.
    This uses neither target-cell polygons nor the weight matrix.
    """
    p = np.asarray(ring)
    delta = np.roll(p, -1, axis=0) - p
    active = delta[:, 1] != 0
    x, y = p[active].T
    dx, dy = delta[active].T
    pieces = []
    for row, valid in enumerate(grid.valid):
        edges = np.flatnonzero(np.diff(np.r_[False, valid, False]))
        endpoints = np.sort([(row-y)/dy, (row+1-y)/dy], axis=0).clip(0, 1)
        hits = endpoints[1] > endpoints[0]
        lo, hi = endpoints[:, hits]
        px, vx, vy = x[hits], dx[hits], dy[hits]
        for left, right in edges.reshape(-1, 2):
            # Split wherever the clamped x function changes slope; trapezoids
            # are exact on each of the resulting linear edge segments.
            splits = [lo, hi]
            for side in (left, right):
                crossing = np.divide(side-px, vx, out=lo.copy(), where=vx != 0)
                splits.append(np.clip(crossing, lo, hi))
            t = np.sort(splits, axis=0)
            f = np.clip(px + t*vx-left, 0, right-left)
            pieces.append(abs(float(np.sum((f[1:]+f[:-1])*0.5*np.diff(t, axis=0)*vy))))
    return math.fsum(pieces)*grid.cell_area


@dataclass
class MappedMeasurement:
    values: np.ndarray
    covered_m2: np.ndarray
    coverage_fraction: np.ndarray
    source_valid: np.ndarray
    contributors: tuple
    source_integral: float
    mapped_integral: float
    unit: str
    integral_unit: str


class FootprintMap:
    """Reusable native-pixel overlap areas and a separately integrated source-domain reference."""

    def __init__(self, grid: WorkingGrid, records: list[RainfallRecord]):
        self.grid = grid
        self.layout = layout_key(records)
        if not records or len({r.source for r in records}) != 1 or len({r.geometry["crs"] for r in records}) != 1:
            raise ValueError("a footprint map needs one source and native CRS")
        self.source = records[0].source
        self.geometry, self.area, self.domain_area = {}, {}, {}
        for record in sorted(records, key=pixel_key):
            key, g = pixel_key(record), record.geometry
            if key in self.geometry:
                raise ValueError(f"duplicate native pixel {key}")
            w, s, e, n = g["footprint"]
            for other, geometry in self.geometry.items():
                ow, os, oe, on = geometry["footprint"]
                overlap = (max(w,ow), max(s,os), min(e,oe), min(n,on))
                if overlap[0] < overlap[2] and overlap[1] < overlap[3]:
                    shared = _domain_area(projected_ring(overlap, g["crs"], grid), grid)
                    if shared > AREA_ATOL:
                        raise ValueError(f"overlapping native pixels {other} and {key}: {shared:g} m²")
            self.geometry[key] = g
            ring = projected_ring(g["footprint"], g["crs"], grid)
            self.area[key] = _cell_areas(ring, grid)
            self.domain_area[key] = _domain_area(ring, grid)
            if not math.isclose(self.area[key].sum(), self.domain_area[key], rel_tol=RTOL, abs_tol=AREA_ATOL):
                raise ValueError(f"independent footprint area check failed for {key}")
        if np.any(sum(self.area.values()) > grid.cell_area + AREA_ATOL):
            raise ValueError("source footprints exceed target cell area")

    def map(self, records: list[RainfallRecord], measurement: str) -> MappedMeasurement:
        """Map one timestamp; absent, missing and unsupported measurements never contribute."""
        if not records or len({r.timestamp_utc or r.reported_date for r in records}) != 1:
            raise ValueError("one observed timestamp per mapping call required")
        specs = {(MOSDAC, "rate"): ("rainfall_rate", "original_value", "mm/h"),
                 (MOSDAC, "derived_depth"): ("rainfall_rate", "derived_value", "mm"),
                 (IMD, "daily_depth"): ("daily_accumulation", "original_value", "mm")}
        if (self.source, measurement) not in specs:
            raise ValueError("measurement incompatible with rainfall source")
        kind, field, unit = specs[self.source, measurement]
        covered = np.zeros(self.grid.valid.shape)
        weighted = np.zeros_like(covered)
        inputs, contributors, seen = [], [], set()
        for r in records:
            key = pixel_key(r)
            if (r.source != self.source or r.measurement_type != kind or key in seen
                    or key not in self.geometry or self.geometry[key]["crs"] != r.geometry["crs"]
                    or tuple(self.geometry[key]["footprint"]) != tuple(r.geometry["footprint"])):
                raise ValueError("mixed source, duplicate pixel, or incompatible layout/measurement")
            seen.add(key)
            value = getattr(r, field)
            if value is None or r.missing:
                continue
            if unit != (r.derived_unit if field == "derived_value" else r.original_unit):
                raise ValueError("unexpected native measurement unit")
            covered += self.area[key]
            weighted += self.area[key]*value
            inputs.append(self.domain_area[key]*value/1000)
            contributors.append(key)
        valid = covered > 0
        values = np.divide(weighted, covered, out=np.full_like(covered, np.nan), where=valid)
        fraction = np.minimum(covered/self.grid.cell_area, 1.0)
        reference = math.fsum(inputs)
        mapped = float(np.sum(values[valid]*covered[valid], dtype=np.float64))/1000
        if not math.isclose(reference, mapped, rel_tol=RTOL, abs_tol=INTEGRAL_ATOL):
            raise ValueError(f"{measurement} conservation failed: {reference} vs {mapped}")
        return MappedMeasurement(values, covered, fraction, valid, tuple(sorted(contributors)),
                                 reference, mapped, unit, "m³/h" if unit == "mm/h" else "m³")
