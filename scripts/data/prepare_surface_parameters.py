"""Prepare native-footprint land cover and provisional pervious soil capacities for P3."""
import json
import math
from pathlib import Path
import sys
from uuid import uuid4

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window, from_bounds
from rasterio.warp import transform, transform_bounds, transform_geom

from acquire_surface_sources import DEM, RAW, ROOT, SOIL_LAYERS, publish_directory
from run_manifest import checksum
from spatial_runoff import CLASSES, SCENARIOS

sys.path.insert(0, str(ROOT / "backend"))
from app.rainfall.spatial import _clip

CONFIG = ROOT / "config/spatial_runoff.json"
OSM = ROOT / "data/roads/raw/bellandur_highways_overpass.json"
OUTPUT = ROOT / "data/landcover/processed"
NODATA = -9999.


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_ref(path):
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": checksum(path)}


def fraction_map(source, target, valid, legend):
    """Intersect native pixel quadrilaterals with target cells in target pixel coordinates."""
    box = transform_bounds(target.crs, source.crs, *target.bounds, densify_pts=41)
    win = from_bounds(*box, transform=source.transform)
    x0, y0 = max(0, math.floor(win.col_off)-1), max(0, math.floor(win.row_off)-1)
    x1 = min(source.width, math.ceil(win.col_off+win.width)+1)
    y1 = min(source.height, math.ceil(win.row_off+win.height)+1)
    fractions = np.zeros((len(CLASSES), *valid.shape))
    if x1 > x0 and y1 > y0:
        pixels = source.read(1, masked=True, window=Window(x0, y0, x1-x0, y1-y0))
        rows, cols = np.mgrid[y0:y1+1, x0:x1+1]
        a = source.transform
        xs, ys = transform(source.crs, target.crs, (a.a*cols+a.b*rows+a.c).ravel(),
                           (a.d*cols+a.e*rows+a.f).ravel())
        inverse = ~target.transform
        xs, ys = np.reshape(xs, rows.shape), np.reshape(ys, rows.shape)
        px = inverse.a*xs + inverse.b*ys + inverse.c
        py = inverse.d*xs + inverse.e*ys + inverse.f
        for r, c in zip(*np.where(~np.ma.getmaskarray(pixels))):
            category = legend.get(str(int(pixels.data[r,c])))
            if category is None:
                raise ValueError(f"Undocumented land-cover class {pixels.data[r,c]}")
            layer = fractions[CLASSES.index(category)]
            ring = [(px[i,j], py[i,j]) for i,j in ((r,c),(r,c+1),(r+1,c+1),(r+1,c))]
            xx, yy = zip(*ring)
            for y in range(max(0, math.floor(min(yy))), min(valid.shape[0], math.ceil(max(yy)))):
                strip = _clip(_clip(ring, 1, y, True), 1, y+1, False)
                for x in range(max(0, math.floor(min(xx))), min(valid.shape[1], math.ceil(max(xx)))):
                    if not valid[y,x]:
                        continue
                    poly = _clip(_clip(strip, 0, x, True), 0, x+1, False)
                    local = [(i-x,j-y) for i,j in poly]
                    layer[y,x] += abs(math.fsum(i*v-j*u for (i,j),(u,v)
                                               in zip(local, local[1:]+local[:1])))*0.5
    covered = fractions.sum(axis=0)
    if np.any(covered[valid] > 1+1e-9):
        raise ValueError("Overlapping land-cover footprints exceed cell area")
    complete = valid & (np.abs(covered-1) <= 1e-12)
    fractions[:, complete] /= covered[complete]
    fractions[CLASSES.index("source_missing")] = np.where(complete, 0., np.maximum(0., 1-covered))
    fractions[:, ~valid] = NODATA
    return fractions


def soil_conversion(layer, raw):
    factor, unit = {"sand": (.1, "%"), "silt": (.1, "%"), "clay": (.1, "%"),
                    "bdod": (.01, "g/cm3"), "soc": (.1, "g/kg")}[layer.split("_")[0]]
    return raw * factor, unit


def cosby_mm_h(sand_percent):
    sand = np.asarray(sand_percent)
    if np.any(~np.isfinite(sand) | (sand < 0) | (sand > 100)):
        raise ValueError("Sand percentage outside physical bounds")
    return 25.4 * 10.**(-0.884 + 0.0153*sand)


def read_soil(paths, target, valid):
    """Look up native values and geometric support at working-cell centres.

    `inside` distinguishes an archive/tile-coverage fault from a provider
    NoData value.  It must remain separate from property validity.
    """
    result = np.full(valid.shape, np.nan)
    inside_any_tile = np.zeros(valid.shape, dtype=bool)
    rows, cols = np.where(valid)
    xs, ys = rasterio.transform.xy(target.transform, rows, cols)
    for path in paths:
        with rasterio.open(path) as ds:
            xx, yy = transform(target.crs, ds.crs, np.atleast_1d(xs), np.atleast_1d(ys))
            rr, cc = rasterio.transform.rowcol(ds.transform, xx, yy)
            inside = (rr>=0) & (cc>=0) & (rr<ds.height) & (cc<ds.width)
            if not inside.any():
                continue
            r, c = rr[inside], cc[inside]
            win = Window(c.min(), r.min(), c.max()-c.min()+1, r.max()-r.min()+1)
            values = ds.read(1, window=win, masked=True).astype(float).filled(np.nan)
            result[rows[inside], cols[inside]] = values[r-r.min(), c-c.min()]
            inside_any_tile[rows[inside], cols[inside]] = True
    return result, inside_any_tile


def road_evidence(target, valid):
    data = read_json(OSM)
    ways = [w for w in data["elements"] if w["type"]=="way"]
    paved = {"asphalt", "paved", "concrete", "concrete:plates", "paving_stones", "sett"}
    lines = []
    for w in ways:
        if w["tags"].get("surface") in paved:
            geom = {"type": "LineString", "coordinates": [(p["lon"], p["lat"]) for p in w["geometry"]]}
            lines.append(transform_geom("EPSG:4326", target.crs, geom))
    presence = rasterize(lines, out_shape=valid.shape, transform=target.transform, all_touched=True)
    return presence, {"ways": len(ways), "tagged_paved_ways": len(lines),
                      "ways_with_width": sum("width" in w["tags"] for w in ways),
                      "paved_road_presence_cells": int(np.count_nonzero(presence[valid])),
                      "osm_base": data["osm3s"]["timestamp_osm_base"], "licence": "ODbL",
                      "meaning": "Positive centreline evidence only. Widths and event-date coverage unknown."}


def prepare():
    config = read_json(CONFIG)
    raw_files, sources = {}, {}
    for key in ["worldcover_2021_v200", *SOIL_LAYERS]:
        source_path = RAW / key / "source.json"
        src = read_json(source_path)
        files = []
        for item in src["files"]:
            path = source_path.parent / item["file"]
            if checksum(path) != item["sha256"]:
                raise ValueError(f"Raw checksum mismatch for {path}")
            if path.suffix == ".tif":
                files.append(path)
        raw_files[key] = files
        sources[key] = file_ref(source_path)
    target_dir = OUTPUT / str(uuid4())
    with publish_directory(target_dir) as directory, rasterio.open(DEM) as target:
        valid = target.read_masks(1) != 0
        products = {}
        def save(name, bands, names, units):
            path = directory / (name+".tif")
            bands = np.asarray(bands, dtype="float64").copy()
            bands[:,~valid] = NODATA
            profile = dict(driver="GTiff", width=target.width, height=target.height, count=len(bands),
                           crs=target.crs, transform=target.transform, dtype="float64", nodata=NODATA,
                           compress="deflate", predictor=3)
            with rasterio.open(path, "w", **profile) as ds:
                ds.write(np.where(np.isfinite(bands), bands, NODATA))
                ds.descriptions = tuple(names)
                ds.units = tuple(units)
            products[name] = {"path": (target_dir/path.name).relative_to(ROOT).as_posix(), "sha256": checksum(path)}

        with rasterio.open(raw_files["worldcover_2021_v200"][0]) as cover:
            fractions = fraction_map(cover, target, valid, config["worldcover_classes"])
        if not np.allclose(fractions[:,valid].sum(axis=0), 1, atol=1e-9, rtol=0):
            raise ValueError("Surface fractions do not cover the valid domain")
        save("fractions", fractions, CLASSES, ["1"]*len(CLASSES))
        pervious = np.clip(sum(fractions[CLASSES.index(k)] for k in config["infiltration_eligible_classes"]), 0, 1)
        save("runoff", [1-pervious, pervious], ["direct_surface_fraction","pervious_fraction"], ["1","1"])
        presence, roads = road_evidence(target, valid)
        save("paved_road_evidence", [presence], ["tagged_paved_centreline_presence"], ["1"])
        soils, soil_geometry, units = {}, {}, []
        for layer in SOIL_LAYERS:
            raw_values, geometric_support = read_soil(raw_files[layer], target, valid)
            values, unit = soil_conversion(layer, raw_values)
            soils[layer] = values
            soil_geometry[layer] = geometric_support
            units.append(unit)
        save("soil_attributes", list(soils.values()), list(soils), units)
        scenario_layers = [config["scenarios"][scenario] for scenario in SCENARIOS]
        # A selectable sensitivity scenario must not turn a missing quantile
        # into an apparently supported capacity.  Support therefore requires
        # all three sand predictions used by the published scenarios.
        scenario_sand_supported = np.logical_and.reduce([np.isfinite(soils[layer]) for layer in scenario_layers])
        scenario_sand_covered = np.logical_and.reduce([soil_geometry[layer] for layer in scenario_layers])
        capacities = []
        for scenario in SCENARIOS:
            sand = soils[config["scenarios"][scenario]]
            capacity = np.full(valid.shape, np.nan)
            known = valid & scenario_sand_supported
            capacity[known] = cosby_mm_h(sand[known])
            capacities.append(capacity)
        # Zero infiltration credit on unsupported soil is the upper-runoff assumption.
        save("infiltration", np.nan_to_num(capacities), SCENARIOS, ["mm/h"]*len(SCENARIOS))
        save("soil_support", np.isfinite(capacities), SCENARIOS, ["1"]*len(SCENARIOS))
        sand_source_covered = scenario_sand_covered
        sand_supported = scenario_sand_supported
        provenance = np.where(sand_supported, 1, np.where(sand_source_covered, 2, 3))
        # 1 = SoilGrids-supported then pedotransfer-derived; 2 = provider
        # NoData; 3 = source archive/tile coverage failure.  Codes 2/3 remain
        # hydraulically unknown and are never substituted into a capacity.
        save("soil_coverage", [sand_source_covered, sand_supported, provenance],
             ["sand_geometric_coverage", "sand_property_support", "infiltration_provenance_code"],
             ["1", "1", "1"])
        metadata = {"version": config["version"], "config": file_ref(CONFIG), "source_dem": file_ref(DEM),
                    "preparation_code": [file_ref(Path(__file__).resolve()),
                                         file_ref(ROOT/"scripts/data/acquire_surface_sources.py"),
                                         file_ref(ROOT/"backend/app/rainfall/spatial.py")],
                    "sources": sources, "raw_tiles": {k:[file_ref(p) for p in fs] for k,fs in raw_files.items()},
                    "products": products, "assumptions": config, "osm": {**file_ref(OSM), **roads},
                    "valid_cells": int(valid.sum()), "nodata_cells": int((~valid).sum()),
                    "class_mean_fractions": dict(zip(CLASSES,fractions[:,valid].mean(axis=1).tolist())),
                    "soil_valid_cells": {k:int(np.isfinite(v).sum()) for k,v in soils.items()},
                    "soil_coverage": {"sand_source_supported_cells": int(sand_supported.sum()),
                                      "sand_provider_nodata_cells": int((valid & sand_source_covered & ~sand_supported).sum()),
                                      "sand_outside_acquired_tiles_cells": int((valid & ~sand_source_covered).sum()),
                                      "infiltration_provenance_codes": {
                                          "1": "SoilGrids 0-5 cm sand prediction; Cosby pedotransfer-derived capacity",
                                          "2": "provider NoData; hydraulic capacity unknown",
                                          "3": "outside acquired source tiles; acquisition failure, not soil NoData"}},
                    "soil_units": dict(zip(soils, units)),
                    "soil_ranges": {k: [float(np.nanmin(v)),float(np.nanmax(v))] if np.isfinite(v).any()
                                    else None for k,v in soils.items()}}
        (directory/"manifest.json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
    return target_dir / "manifest.json"


if __name__ == "__main__":
    print(prepare())
