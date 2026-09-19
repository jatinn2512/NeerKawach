"""Download the public NASA/USGS SRTM 1 arc-second tile for Bellandur.

The raw HGT tile is preserved. No terrain derivatives or hydrologic processing are
performed here; this is intentionally a P1 acquisition/metadata script.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import struct
import urllib.request
from datetime import date
from pathlib import Path

from p1_common import ROOT, load_study_area


URL = "https://s3.amazonaws.com/elevation-tiles-prod/skadi/N12/N12E077.hgt.gz"
RAW_PATH = ROOT / "data" / "dem" / "raw" / "N12E077.hgt.gz"
METADATA_PATH = ROOT / "data" / "dem" / "metadata" / "srtm_n12e077.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_hgt(path: Path, bbox: dict) -> tuple[int, int, int, int, list[int]]:
    """Return dimensions, nodata count, tile range and in-area range in metres."""
    with gzip.open(path, "rb") as handle:
        payload = handle.read()
    cell_count = len(payload) // 2
    side = int(cell_count**0.5)
    if side * side != cell_count:
        raise ValueError(f"Unexpected HGT payload size: {len(payload)} bytes")
    values = struct.unpack(f">{cell_count}h", payload)
    valid = [value for value in values if value != -32768]
    if not valid:
        raise ValueError("DEM contains no valid elevation cells")
    south, west, north, east = bbox["min_lat"], bbox["min_lon"], bbox["max_lat"], bbox["max_lon"]
    in_area = []
    for row in range(side):
        latitude = 13.0 - row / 3600.0
        if not (south <= latitude <= north):
            continue
        for column in range(side):
            longitude = 77.0 + column / 3600.0
            if west <= longitude <= east:
                value = values[row * side + column]
                if value != -32768:
                    in_area.append(value)
    if not in_area:
        raise ValueError("DEM has no valid cells inside the study area")
    return side, side, len(values) - len(valid), min(valid), max(valid), [min(in_area), max(in_area)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="redownload an existing raw file")
    args = parser.parse_args()
    area = load_study_area()
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if args.force or not RAW_PATH.exists():
        request = urllib.request.Request(URL, headers={"User-Agent": "FloodOps-P1/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response, RAW_PATH.open("wb") as handle:
            handle.write(response.read())
    rows, cols, nodata_count, minimum, maximum, study_range = inspect_hgt(RAW_PATH, area["bbox"])
    metadata = {
        "dataset": "NASA/USGS SRTMGL1.003 via AWS Terrain Tiles",
        "source_url": URL,
        "download_date_utc": date.today().isoformat(),
        "raw_file": str(RAW_PATH.relative_to(ROOT)).replace("\\", "/"),
        "sha256": sha256(RAW_PATH),
        "tile_extent": {"min_lat": 12.0, "min_lon": 77.0, "max_lat": 13.0, "max_lon": 78.0},
        "study_area_covered": area["bbox"],
        "crs": "EPSG:4326",
        "horizontal_resolution": "1 arc-second (~30 m at the equator; ~27 m east-west at Bellandur)",
        "rows": rows,
        "columns": cols,
        "nodata_value": -32768,
        "elevation_units": "metres",
        "vertical_reference": "SRTM elevation values; consult SRTM product documentation before hydrologic use",
        "valid_elevation_range_m": [minimum, maximum],
        "study_area_elevation_range_m": study_range,
        "nodata_cell_count": nodata_count,
        "processing_performed": "Downloaded and inspected raw HGT only; no clipping, resampling or terrain derivatives.",
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
