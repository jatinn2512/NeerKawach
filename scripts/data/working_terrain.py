"""Terrain-only D8 products derived on the exact P3 elevation grid."""

from collections import deque
import json
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

from derive_terrain import (
    D8_DIRECTIONS, DEPRESSION_NODATA, INTEGER_NODATA, classify_depressions,
    contributing_cells_and_terminals, sha256, steepest_d8, write_raster,
)


ALGORITHM = "working-dem-strict-d8-v1"
SINK_TYPES = ("routable", "local_minimum", "flat_or_tied_sink", "boundary_sink")


def connected_flats(dem, valid, direction):
    """Label maximal 8-connected equal-elevation groups, including their draining lips."""
    regions = np.where(valid, 0, INTEGER_NODATA).astype(np.int32)
    visited = ~valid.copy()
    groups = []
    for row, col in zip(*np.where(valid)):
        if visited[row, col]:
            continue
        cells = [(int(row), int(col))]
        visited[row, col] = True
        queue = deque(cells)
        while queue:
            r, c = queue.popleft()
            for dr, dc, _, _ in D8_DIRECTIONS:
                y, x = r + dr, c + dc
                if not (0 <= y < dem.shape[0] and 0 <= x < dem.shape[1]):
                    continue
                if not visited[y, x] and dem[y, x] == dem[r, c]:
                    visited[y, x] = True
                    queue.append((y, x))
                    cells.append((y, x))
        if len(cells) > 1:
            group_id = len(groups) + 1
            rr, cc = zip(*cells)
            regions[rr, cc] = group_id
            groups.append({"id": group_id, "cells": len(cells), "elevation_m": float(dem[row, col]),
                           "cells_with_direct_descent": int(np.count_nonzero(direction[rr, cc] > 0))})
    return regions, groups


def write_working_terrain(root: Path, dem_path: Path, directory: Path) -> dict:
    with rasterio.open(dem_path) as ds:
        if not ds.crs or not ds.crs.is_projected:
            raise ValueError("Working D8 requires a projected DEM")
        dem = ds.read(1).astype(np.float64)
        valid = (ds.read_masks(1) != 0) & np.isfinite(dem)
        if not valid.any():
            raise ValueError("Working DEM has no valid elevations")
        transform, crs, profile = ds.transform, ds.crs, ds.profile.copy()
        metric = Affine.scale(crs.linear_units_factor[1]) * transform
    direction = steepest_d8(dem, valid, metric)
    counts, terminal = contributing_cells_and_terminals(direction, valid)
    sink_class, _ = classify_depressions(dem, valid, direction)
    flats, groups = connected_flats(dem, valid, direction)
    area = abs(metric.determinant)
    source_hash = sha256(dem_path)
    tags = {"ALGORITHM": ALGORITHM, "SOURCE_DEM_SHA256": source_hash}
    layers = [
        ("flow_direction", direction, INTEGER_NODATA, "D8 code"),
        ("flow_accumulation", counts, INTEGER_NODATA, "cells including focal cell"),
        ("contributing_area", np.where(valid, counts * area, -9999.), -9999., "m2"),
        ("depressions", sink_class, DEPRESSION_NODATA, "0=routable 1=minimum 2=flat/tied 3=boundary sink"),
        ("flat_region", flats, INTEGER_NODATA, "flat region ID, 0=singleton"),
        ("terminal_cell", terminal, INTEGER_NODATA, "provisional terminal ID = 1 + row * width + column"),
    ]
    products = {}
    for key, values, nodata, units in layers:
        path = directory / f"{key}_working.tif"
        write_raster(path, values, profile, values.dtype.name, nodata, {**tags, "UNITS": units})
        products[key] = {"file": path.relative_to(root).as_posix(), "sha256": sha256(path),
                         "dtype": values.dtype.name, "nodata": nodata}
    flat_path = directory / "flat_regions.json"
    flat_path.write_text(json.dumps(groups, indent=2) + "\n", encoding="utf-8")
    path = directory / "terrain_hydrology.json"
    metadata = {
        "algorithm": ALGORITHM, "source_dem": dem_path.relative_to(root).as_posix(),
        "source_dem_sha256": source_hash, "shape_rows_columns": list(dem.shape),
        "affine_abcdef": list(transform[:6]), "crs": str(crs), "cell_area_m2": area,
        "direction_codes": {str(code): [dr, dc] for dr, dc, code, _ in D8_DIRECTIONS},
        "tie_order": [code for _, _, code, _ in D8_DIRECTIONS], "unresolved_code": 0,
        "valid_cells": int(valid.sum()), "nodata_cells": int((~valid).sum()),
        "terrain_classes": {name: int(np.sum(sink_class == i)) for i, name in enumerate(SINK_TYPES)},
        "unresolved_cells": int(np.sum(valid & (direction == 0))),
        "flat_region_count": len(groups), "flat_region_cells": sum(group["cells"] for group in groups),
        "flat_inventory": flat_path.relative_to(root).as_posix(),
        "terminal_contributing_cells": int(counts[valid & (direction == 0)].sum()),
        "outlet_status": "unverified terrain terminals",
        "metadata_file": path.relative_to(root).as_posix(), "products": products,
    }
    path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata
