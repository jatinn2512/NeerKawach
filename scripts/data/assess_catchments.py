"""Assess a run's terrain graph against Bellandur's archived terrain and P4 candidates."""

import argparse
from collections import Counter
import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import rowcol
from rasterio.warp import transform, transform_geom

from derive_terrain import D8_BY_CODE, classify_depressions, load_json, sha256, write_low_points
from run_manifest import simulation_run
from working_terrain import SINK_TYPES


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "data/dem/processed/bellandur_dem_buffered.tif"
NATIVE_D8 = ROOT / "data/dem/terrain/flow_direction.tif"
OLD_POINTS = ROOT / "data/dem/terrain/low_points.geojson"
LEGACY = ROOT / "data/surface_routing/input"
P4 = ROOT / "data/drainage/processed"
AREA = ROOT / "config/study_area.json"


def corrected_points(path):
    with rasterio.open(NATIVE) as dem, rasterio.open(NATIVE_D8) as d8:
        if (dem.shape, dem.crs, dem.transform) != (d8.shape, d8.crs, d8.transform):
            raise ValueError("Native D8 and DEM registration disagree")
        _, features = classify_depressions(dem.read(1), dem.read_masks(1) != 0, d8.read(1))
        west, south, east, north = dem.bounds
        write_low_points(features, dem.transform, dict(min_lon=west, min_lat=south, max_lon=east, max_lat=north), path)
        old_features = load_json(OLD_POINTS)["features"]
        old = {f["id"]: f for f in old_features}
        corrected = load_json(path)["features"]
        if len(old_features) != len(old) or {f["id"] for f in corrected} != old.keys():
            raise ValueError("Native low-point identities changed")
        offsets = []
        for f in corrected:
            p = f["properties"]
            centre = dem.xy(p["row"], p["column"])
            earlier = old[f["id"]]
            if (not np.allclose(centre, f["geometry"]["coordinates"], atol=1e-12, rtol=0)
                    or any(p[k] != v for k, v in earlier["properties"].items())):
                raise ValueError("Native low-point centre or properties disagree")
            offsets.append(np.subtract(earlier["geometry"]["coordinates"], centre))
    return {"verified_centres": len(corrected), "old_minus_centre_min_degrees": np.min(offsets, axis=0).tolist(),
            "old_minus_centre_max_degrees": np.max(offsets, axis=0).tolist()}


def perimeter(mask):
    padded = np.pad(mask, 1)
    interior = mask.copy()
    rows, cols = mask.shape
    for dr, dc, _ in D8_BY_CODE.values():
        interior &= padded[1+dr:1+dr+rows, 1+dc:1+dc+cols]
    return mask & ~interior


def path_statistics(direction, dem, valid, study):
    """Follow each source independently, including malformed legacy endings."""
    study_edge, terrain_edge = perimeter(study), perimeter(valid)
    rows, cols = valid.shape
    terms, edges, zero_classes = Counter(), Counter(), Counter()
    touched = left = at_edge = study_at_edge = 0
    for start_r, start_c in zip(*np.where(valid)):
        r, c = start_r, start_c
        touched_study_edge = left_study = False
        seen = set()
        while 0 <= r < rows and 0 <= c < cols and valid[r, c]:
            touched_study_edge |= bool(study_edge[r, c])
            left_study |= not study[r, c]
            code = int(direction[r, c])
            if code == 0:
                terms["unresolved_terminal"] += 1
                at_edge += int(terrain_edge[r, c])
                study_at_edge += int(study[start_r, start_c] and terrain_edge[r, c])
                if not seen:
                    neighbours = [dem[r+dr, c+dc] for dr, dc, _ in D8_BY_CODE.values()
                                  if 0 <= r+dr < rows and 0 <= c+dc < cols and valid[r+dr, c+dc]]
                    if any(z < dem[r,c] for z in neighbours):
                        kind = "has_lower_neighbour"
                    elif terrain_edge[r,c]:
                        kind = "boundary_sink"
                    elif dem[r,c] in neighbours:
                        kind = "flat_or_tied_sink"
                    else:
                        kind = "local_minimum"
                    zero_classes[kind] += 1
                break
            if (r, c) in seen:
                terms["cycle"] += 1
                break
            dr, dc, _ = D8_BY_CODE[code]
            y, x = r+dr, c+dc
            if not seen:
                if not (0 <= y < rows and 0 <= x < cols and valid[y, x]):
                    edges["outside_valid"] += 1
                else:
                    drop = float(dem[r, c]) - float(dem[y, x])
                    edges["downhill" if drop > 0 else "uphill" if drop < 0 else "level"] += 1
            seen.add((r, c))
            r, c = y, x
        else:
            terms["outside_valid"] += 1
            left_study = True
        if study[start_r, start_c]:
            touched += int(touched_study_edge)
            left += int(left_study)
    return {"directed_edges": dict(edges), "source_path_destinations": dict(terms),
            "zero_code_classes_on_working_dem": dict(zero_classes),
            "sources_ending_at_buffer_mask_edge": at_edge, "study_sources": int(study.sum()),
            "study_paths_touching_study_edge": touched, "study_paths_leaving_study": left,
            "study_sources_ending_at_buffer_mask_edge": study_at_edge}


def assess(metadata_path):
    meta = load_json(metadata_path)
    dem_path = ROOT / meta["source_dem"]
    files = {k: ROOT / v["file"] for k, v in meta["products"].items()}
    old_d8 = LEGACY / "flow_direction_working.tif"
    old_acc = LEGACY / "flow_accumulation_working.tif"
    connections = P4 / "surface_drainage_connections.geojson"
    nodes = P4 / "drainage_nodes.geojson"
    run_id = str(uuid4())
    output = ROOT / "data/runs" / run_id / "assessment"
    inputs = [metadata_path, dem_path, *files.values(), NATIVE, NATIVE_D8, OLD_POINTS, old_d8,
              old_acc, LEGACY / "dem_working.tif", nodes, connections]
    with simulation_run(ROOT, "P2", inputs, [output], [AREA], run_id=run_id) as manifest:
        if (sha256(dem_path) != meta["source_dem_sha256"] or sha256(LEGACY / "dem_working.tif") != sha256(dem_path)
                or any(sha256(f) != meta["products"][key]["sha256"] for key, f in files.items())):
            raise ValueError("Terrain product checksum or comparison DEM mismatch")
        output.mkdir()
        registration = corrected_points(output / "low_points.geojson")
        with rasterio.open(dem_path) as ds:
            dem, valid, affine, crs = ds.read(1), ds.read_masks(1) != 0, ds.transform, ds.crs
        def layer(path):
            with rasterio.open(path) as ds:
                if (ds.shape, ds.transform, ds.crs) != (valid.shape, affine, crs):
                    raise ValueError(f"Grid mismatch at {path}")
                return ds.read(1)
        bbox = load_json(AREA)["bbox"]
        w, s, e, n = (bbox[k] for k in ("min_lon", "min_lat", "max_lon", "max_lat"))
        polygon = {"type": "Polygon", "coordinates": [[[w,s],[e,s],[e,n],[w,n],[w,s]]]}
        study = valid & geometry_mask([transform_geom("EPSG:4326", crs, polygon)], out_shape=valid.shape,
                                      transform=affine, invert=True)
        counts, areas = layer(files["flow_accumulation"]), layer(files["contributing_area"])
        sinks, terminal = layer(files["depressions"]), layer(files["terminal_cell"])
        direction = layer(files["flow_direction"])
        terminals = [{"row": int(r), "column": int(c), "terminal_id": int(terminal[r,c]),
                      "type": SINK_TYPES[sinks[r,c]], "contributing_cells": int(counts[r,c]),
                      "provisional_area_m2": float(areas[r,c])} for r,c in zip(*np.where(valid & (direction == 0)))]
        def candidate(lon, lat):
            xs, ys = transform("EPSG:4326", crs, [lon], [lat])
            r, c = map(int, rowcol(affine, xs[0], ys[0]))
            if not (0 <= r < valid.shape[0] and 0 <= c < valid.shape[1] and valid[r,c]):
                return {"terrain_status": "outside_valid_terrain"}
            return {"row": r, "column": c, "terrain_status": SINK_TYPES[sinks[r,c]],
                    "upstream_cells": int(counts[r,c]), "upstream_area_m2": float(areas[r,c]),
                    "downstream_terminal_id": int(terminal[r,c])}
        candidates = []
        for f in load_json(connections)["features"]:
            p = f["properties"]
            candidates.append({"id": f["id"], "source": p["source"], "native_surface_cell": p["surface_cell_id"],
                               "mapped_node": p["drainage_node_id"], "connection_confidence": p["confidence"],
                               "connection_method": p["method"], **candidate(p["surface_longitude"], p["surface_latitude"])})
        for f in load_json(nodes)["features"]:
            p = f["properties"]
            if p["status"] == "outfall_candidate":
                candidates.append({"id": p["node_id"], "source": p["source"], "status": p["status"],
                                   "basis": p["metadata"]["basis"], **candidate(*f["geometry"]["coordinates"][:2])})
        report = {"terrain_metadata": metadata_path.relative_to(ROOT).as_posix(), "native_registration": registration,
                  "interpretation": "Terrain contributions over the valid buffered DEM. A cell match supplies no hydraulic connection.",
                  "physical_outlets_confirmed": 0, "paths_without_confirmed_outlet": int(valid.sum()),
                  "boundary_definition": "Study polygon by cell centre. Edge means eight-neighbour contact with outside the mask.",
                  "legacy": path_statistics(layer(old_d8), dem, valid, study),
                  "working_dem": path_statistics(direction, dem, valid, study),
                  "accumulation_percentiles": {"percentiles": [0,50,90,95,99,100],
                      "transferred_native_counts": np.percentile(layer(old_acc)[valid], [0,50,90,95,99,100]).tolist(),
                      "recomputed_counts": np.percentile(counts[valid], [0,50,90,95,99,100]).tolist()},
                  "p4_candidates": candidates, "provisional_terminals": terminals}
        (output / "catchments.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        manifest["terrain_hydrology"] = meta
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terrain-metadata", required=True, type=Path)
    print(assess(parser.parse_args().terrain_metadata.resolve()))
