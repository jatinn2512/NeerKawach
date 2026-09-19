"""Normalize station/grid rainfall CSVs into the provider-neutral P1 schema.

Expected canonical output columns are timestamp, latitude, longitude,
rainfall_mm, source. Station metadata is retained in a sidecar JSON and source
metadata is never converted into a false finer spatial resolution.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from p1_common import ROOT, load_study_area


def parse_timestamp(value: str) -> str:
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize(input_path: Path, output_path: Path, source: str, column_map: dict[str, str], metadata: dict, spatial_mode: str = "station", grid_resolution: float | None = None) -> dict:
    area = load_study_area()
    required = ("timestamp", "latitude", "longitude", "rainfall_mm")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    counts = {"input": 0, "output": 0, "duplicates": 0, "invalid": 0, "outside_bbox": 0, "missing": 0}
    with input_path.open(newline="", encoding="utf-8-sig") as source_file:
        reader = csv.DictReader(source_file)
        missing_columns = [key for key in required if column_map.get(key) not in (reader.fieldnames or [])]
        if missing_columns:
            raise ValueError(f"Input is missing mapped columns: {missing_columns}")
        with output_path.open("w", newline="", encoding="utf-8") as target_file:
            writer = csv.DictWriter(target_file, fieldnames=[*required, "source"])
            writer.writeheader()
            bbox = area["bbox"]
            for row in reader:
                counts["input"] += 1
                try:
                    timestamp = parse_timestamp(row[column_map["timestamp"]])
                    latitude = float(row[column_map["latitude"]])
                    longitude = float(row[column_map["longitude"]])
                    rainfall = float(row[column_map["rainfall_mm"]])
                    if not all(math.isfinite(value) for value in (latitude, longitude, rainfall)) or rainfall < 0:
                        raise ValueError("invalid numeric rainfall record")
                except (KeyError, TypeError, ValueError):
                    counts["invalid"] += 1
                    continue
                key = (timestamp, latitude, longitude, source)
                if key in seen:
                    counts["duplicates"] += 1
                    continue
                seen.add(key)
                if spatial_mode == "grid":
                    if not grid_resolution or grid_resolution <= 0:
                        raise ValueError("grid mode requires a positive --grid-resolution in degrees")
                    half = grid_resolution / 2
                    covers_area = not (latitude + half < bbox["min_lat"] or latitude - half > bbox["max_lat"] or longitude + half < bbox["min_lon"] or longitude - half > bbox["max_lon"])
                else:
                    covers_area = bbox["min_lat"] <= latitude <= bbox["max_lat"] and bbox["min_lon"] <= longitude <= bbox["max_lon"]
                if not covers_area:
                    counts["outside_bbox"] += 1
                    continue
                writer.writerow({"timestamp": timestamp, "latitude": latitude, "longitude": longitude, "rainfall_mm": rainfall, "source": source})
                counts["output"] += 1
    if counts["output"] == 0:
        raise ValueError("No valid in-area rainfall records were written")
    sidecar = {
        "source": source,
        "input_file": str(input_path.relative_to(ROOT)).replace("\\", "/"),
        "output_file": str(output_path.relative_to(ROOT)).replace("\\", "/"),
        "canonical_crs": "EPSG:4326",
        "schema": required + ["source"],
        "spatial_mode": spatial_mode,
        "grid_resolution_degrees": grid_resolution if spatial_mode == "grid" else None,
        "source_metadata": metadata,
        "validation_counts": counts,
        "normalization": "UTC timestamps; rainfall converted to non-negative millimetres; exact duplicate rows dropped; points outside the canonical bbox excluded",
    }
    metadata_path = output_path.with_suffix(".metadata.json")
    metadata_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return sidecar


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--timestamp-column", default="timestamp")
    parser.add_argument("--latitude-column", default="latitude")
    parser.add_argument("--longitude-column", default="longitude")
    parser.add_argument("--rainfall-column", default="rainfall_mm")
    parser.add_argument("--metadata-json", default="{}")
    parser.add_argument("--spatial-mode", choices=("station", "grid"), default="station")
    parser.add_argument("--grid-resolution", type=float)
    args = parser.parse_args()
    print(json.dumps(normalize(args.input, args.output, args.source, {
        "timestamp": args.timestamp_column, "latitude": args.latitude_column,
        "longitude": args.longitude_column, "rainfall_mm": args.rainfall_column,
    }, json.loads(args.metadata_json), args.spatial_mode, args.grid_resolution), indent=2))


if __name__ == "__main__":
    main()
