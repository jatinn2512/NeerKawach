"""Publish native-time spatial rainfall products to local, source-specific snapshots."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.rainfall.providers.imd import daily_metadata_path, read_daily_grid
from app.rainfall.providers.mosdac import MosdacProvider
from app.rainfall.registry import REGISTRY_PATH, load_registry, relative_path
from app.rainfall.spatial import (AREA_ATOL, EDGE_STEP_DEG, IMD, INELIGIBLE, INTEGRAL_ATOL, MOSDAC,
                                 RTOL, FootprintMap, WorkingGrid, layout_key)
from run_manifest import checksum

GRID_FILE = ROOT / "data/surface_routing/input/working_grid.json"
OUTPUT_ROOT = ROOT / "data/rainfall/mapped"
MEASUREMENTS = {MOSDAC: {"rate": "mm/h", "derived_depth": "mm"}, IMD: {"daily_depth": "mm"}}
METHOD = "Densified native footprints projected to DEM CRS; area-weighted mean on valid covered area."


def source_frames(source, config, grid):
    bbox = grid.geographic_bbox()
    raw = sorted((ROOT / config["raw_directory"]).glob(config["raw_file_pattern"]))
    if not raw:
        raise ValueError(f"no native observation files for {source}")
    inputs = set(raw)
    frames = {}
    for path in raw:
        if source == MOSDAC:
            with rasterio.open(path) as ds:
                records = MosdacProvider.frame(ds, path, bbox, config["native_resolution_m"])
        else:
            control = path.with_name("imd_gpm_template.ctl")
            metadata = daily_metadata_path(path, ROOT / "data/rainfall/metadata")
            inputs.update((control, metadata))
            records = read_daily_grid(path, control, metadata, bbox).records
        if not records:
            raise ValueError(f"no native pixels in the target bounding box for {path.name}")
        timestamp = records[0].timestamp_utc
        if timestamp in frames:
            raise ValueError(f"duplicate source frame {timestamp}")
        frames[timestamp] = records
    gaps = []
    if source == MOSDAC:
        metadata = ROOT / config["metadata_file"]
        inputs.add(metadata)
        archive = json.loads(metadata.read_text(encoding="utf-8"))
        nominal = {f["timestamp_utc"] for f in archive["records"]}
        nominal.update(archive["temporal_coverage"]["missing_timestamps"])
        gaps = sorted(nominal.difference(frames))
    return frames, gaps, inputs


def open_tiff(path, grid, count, dtype, nodata, source, product):
    height, width = grid.valid.shape
    ds = rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=count,
                       dtype=dtype, crs=grid.crs, transform=grid.affine, nodata=nodata,
                       compress="deflate", predictor=3 if dtype == "float64" else 1, interleave="band")
    ds.update_tags(source_id=source, product=product, mapping_method=METHOD,
                   processing_status="complete", provenance="manifest.json")
    return ds


def write_layers(path, grid, source, layers):
    """Static ancillary layers share the target affine and each has its own band unit."""
    with open_tiff(path, grid, len(layers), "float64", np.nan, source, path.stem) as ds:
        for band, (name, unit, values) in enumerate(layers, 1):
            ds.write(np.where(grid.valid, values, np.nan), band)
            ds.set_band_description(band, name)
            ds.set_band_unit(band, unit)


def coverage_stats(mapped, grid):
    area = mapped.covered_m2
    return {"valid_dem_cells": int(grid.valid.sum()), "covered_cells": int(mapped.source_valid.sum()),
            "partial_cells": int(((area > 0) & (area < grid.cell_area-AREA_ATOL)).sum()),
            "uncovered_valid_cells": int((grid.valid & ~mapped.source_valid).sum()),
            "dem_nodata_cells": int((~grid.valid).sum()), "covered_area_m2": float(area.sum()),
            "min_fraction_on_valid_dem": float(mapped.coverage_fraction[grid.valid].min()),
            "max_fraction_on_valid_dem": float(mapped.coverage_fraction[grid.valid].max())}


def build_snapshot(directory, source, grid, grid_metadata, dem, config):
    frames, gaps, inputs = source_frames(source, config, grid)
    inputs.update((REGISTRY_PATH, grid_metadata, dem))
    input_hashes = {relative_path(p): checksum(p) for p in sorted(inputs)}
    target = {"crs": str(grid.crs), "shape_rows_columns": grid.valid.shape,
              "transform_gdal": grid.affine.to_gdal(), "pixel_size_m": [grid.affine.a, -grid.affine.e],
              "cell_area_m2": grid.cell_area, "valid_domain_area_m2": int(grid.valid.sum())*grid.cell_area,
              "dem": relative_path(dem), "grid_metadata": relative_path(grid_metadata), "valid_mask": "dem_valid.tif"}
    manifest = {"schema_version": 1, "source_id": source, "processing_status": "complete",
                "method": METHOD, "geographic_edge_max_step_degrees": EDGE_STEP_DEG, "target_grid": target,
                "independent_reference": "Green's-theorem boundary integral against contiguous valid DEM row runs",
                "tolerance": {"area_absolute_m2": AREA_ATOL, "integral_absolute": INTEGRAL_ATOL, "relative": RTOL},
                "input_sha256": input_hashes, "missing_utc_labels": gaps, "frames": [], "layouts": {},
                "coverage_products": {}, "ineligible_sources": INELIGIBLE,
                "software": {"rasterio": rasterio.__version__, "gdal": rasterio.__gdal_version__,
                             "numpy": np.__version__}}
    with open_tiff(directory/"dem_valid.tif", grid, 1, "uint8", None, source, "DEM validity") as ds:
        ds.write(grid.valid.astype("uint8"), 1)
        ds.set_band_description(1, "1 valid DEM, 0 terrain nodata")
    maps, masks = {}, {}
    with ExitStack() as stack:
        writers = {name: stack.enter_context(open_tiff(directory/f"{name}.tif", grid, len(frames),
                                                       "float64", np.nan, source, name))
                   for name in MEASUREMENTS[source]}
        for band, (timestamp, records) in enumerate(sorted(frames.items()), 1):
            layout = layout_key(records)
            if layout not in maps:
                weights = FootprintMap(grid, records)
                number = len(maps) + 1
                maps[layout] = (number, weights)
                overlaps = f"overlap_{number}.tif"
                layers = [(f"row_{row}_col_{col}", "m2", a) for (row, col), a in weights.area.items()]
                write_layers(directory/overlaps, grid, source, layers)
                manifest["layouts"][number] = {"overlap_raster": overlaps, "pixels": [
                    {"band": i, "pixel": k, "native_geometry": g, "valid_domain_area_m2": weights.domain_area[k]}
                    for i, (k, g) in enumerate(weights.geometry.items(), 1)]}
            number, weights = maps[layout]
            first = records[0]
            frame = {"band": band, "timestamp_utc": timestamp, "source_label": first.source_label,
                     "source_file": first.source_file, "layout": number, "measurements": {},
                     "records": [r.as_dict() for r in records]}
            for name, ds in writers.items():
                mapped = weights.map(records, name)
                support = (number, mapped.contributors)
                if support not in masks:
                    filename = f"coverage_{len(masks)+1}.tif"
                    masks[support] = filename
                    write_layers(directory/filename, grid, source, [
                        ("covered_area_m2", "m2", mapped.covered_m2),
                        ("coverage_fraction", "1", mapped.coverage_fraction),
                        ("source_valid", "1", mapped.source_valid)])
                    manifest["coverage_products"][filename] = {
                        "layout": number, "valid_native_pixels": mapped.contributors, **coverage_stats(mapped, grid)}
                ds.write(mapped.values, band)
                ds.set_band_description(band, timestamp)
                ds.set_band_unit(band, mapped.unit)
                ds.update_tags(band, source_label=first.source_label, source_file=first.source_file,
                               source_sha256=input_hashes[first.source_file], coverage=masks[support],
                               native_variable=first.variable, native_unit=first.original_unit,
                               measurement=name, layout=str(number))
                frame["measurements"][name] = {
                    "raster": f"{name}.tif", "unit": mapped.unit, "coverage": masks[support],
                    "source_integral": mapped.source_integral, "mapped_integral": mapped.mapped_integral,
                    "integral_unit": mapped.integral_unit,
                    "absolute_residual": abs(mapped.source_integral-mapped.mapped_integral)}
            manifest["frames"].append(frame)
    manifest["output_sha256"] = {p.name: checksum(p) for p in sorted(directory.glob("*.tif"))}
    (directory/"manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return manifest


def publish(source, grid, grid_metadata, dem, output_root):
    """Publish a complete immutable snapshot, then atomically update the source pointer."""
    config = load_registry()["sources"][source]
    parent = output_root/source
    parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".building-", dir=parent) as temporary:
        stage = Path(temporary)/"products"
        stage.mkdir()
        manifest = build_snapshot(stage, source, grid, grid_metadata, dem, config)
        digest = checksum(stage/"manifest.json")
        destination = parent/digest[:16]
        try:
            stage.rename(destination)
        except OSError:
            if not destination.is_dir() or checksum(destination/"manifest.json") != digest:
                raise
            if any(checksum(destination/name) != expected for name, expected in manifest["output_sha256"].items()):
                raise ValueError(f"published rainfall snapshot has changed: {destination}")
        pointer = Path(temporary)/"latest.json"
        pointer.write_text(json.dumps({"manifest": f"{destination.name}/manifest.json",
                                       "manifest_sha256": digest}, indent=2)+"\n", encoding="utf-8")
        pointer.replace(parent/"latest.json")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("all", MOSDAC, IMD), default="all")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    grid_metadata = json.loads(GRID_FILE.read_text(encoding="utf-8"))
    dem = ROOT / grid_metadata["outputs"]["dem"]["file"]
    grid = WorkingGrid.read(dem, GRID_FILE)
    for source in (MEASUREMENTS if args.source == "all" else [args.source]):
        path = publish(source, grid, GRID_FILE, dem, args.output_root)
        print(f"{source}: {path / 'manifest.json'}")


if __name__ == "__main__":
    main()
