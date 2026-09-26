"""Acquire and subset one official IMD/NCMRWF daily merged GPM rainfall grid.

This product is a 0.25 degree daily satellite-gauge merged grid, not radar data.
The raw binary and control information are preserved before creating a small
provider-neutral CSV for cells intersecting the Bellandur bbox.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import struct
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from p1_common import ROOT, load_study_area


BASE_URL = "https://www.imdpune.gov.in/cmpg/Realtimedata/gpm/"
RAW_DIR = ROOT / "data" / "rainfall" / "raw" / "imd"
PROCESSED_DIR = ROOT / "data" / "rainfall" / "processed"
METADATA_DIR = ROOT / "data" / "rainfall" / "metadata"
NX, NY = 241, 281
X0, Y0, STEP = 50.0, -30.0, 0.25


def fetch_bytes(url: str, data: bytes | None = None) -> bytes:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": "Neer Kawach-P1/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def decode_values(payload: bytes) -> tuple[str, list[float]]:
    if len(payload) != NX * NY * 4:
        raise ValueError(f"Expected {NX * NY * 4} bytes, received {len(payload)}")
    candidates = []
    for endian in ("<", ">"):
        values = list(struct.unpack(f"{endian}{NX * NY}f", payload))
        usable = [value for value in values if math.isfinite(value) and -999.1 <= value <= 10000]
        candidates.append((len(usable), endian, values))
    _, endian, values = max(candidates, key=lambda item: item[0])
    return endian, values


def cell_intersects(lat: float, lon: float, bbox: dict) -> bool:
    half = STEP / 2
    return not (lat + half < bbox["min_lat"] or lat - half > bbox["max_lat"] or lon + half < bbox["min_lon"] or lon - half > bbox["max_lon"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="IMD date in ddmmyyyy format, e.g. 17092026")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if len(args.date) != 8 or not args.date.isdigit():
        raise ValueError("--date must be ddmmyyyy")
    date_value = datetime.strptime(args.date, "%d%m%Y").date()
    area = load_study_area()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{args.date}.grd"
    ctl_path = RAW_DIR / "imd_gpm_template.ctl"
    output_path = PROCESSED_DIR / f"imd_gpm_{date_value.isoformat()}.csv"
    metadata_path = METADATA_DIR / f"imd_gpm_{date_value.isoformat()}.json"
    if args.force or not raw_path.exists():
        body = urllib.parse.urlencode({"rain": args.date}).encode("ascii")
        raw_path.write_bytes(fetch_bytes(BASE_URL + "rain.php", body))
    if args.force or not ctl_path.exists():
        ctl_path.write_bytes(fetch_bytes(BASE_URL + "dataddmmyyyy.php"))
    payload = raw_path.read_bytes()
    endian, values = decode_values(payload)
    rows = []
    for row in range(NY):
        latitude = Y0 + row * STEP
        for column in range(NX):
            longitude = X0 + column * STEP
            if not cell_intersects(latitude, longitude, area["bbox"]):
                continue
            rainfall = values[row * NX + column]
            if not math.isfinite(rainfall) or rainfall <= -998:
                continue
            rows.append({
                "timestamp": f"{date_value.isoformat()}T00:00:00Z",
                "latitude": f"{latitude:.2f}",
                "longitude": f"{longitude:.2f}",
                "rainfall_mm": f"{rainfall:.3f}",
                "source": "imd_ncmrwf_gpm_merged_daily",
            })
    if not rows:
        raise ValueError("No valid IMD grid cells intersected the Bellandur bbox")
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "source": "IMD/NCMRWF daily merged satellite-gauge rainfall (GPM-based)",
        "provider": "India Meteorological Department and National Centre for Medium Range Weather Forecasting",
        "source_url": BASE_URL + "Rain_Download.html",
        "download_endpoint": BASE_URL + "rain.php",
        "product_date": date_value.isoformat(),
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "spatial_resolution": "0.25 x 0.25 degree",
        "temporal_resolution": "daily; source-specific daily accumulation convention",
        "units": "millimetres per daily accumulation",
        "format": "raw float32 binary grid plus provider control file",
        "crs": "EPSG:4326",
        "grid_crs_description": "Geographic longitude/latitude grid",
        "grid_definition": {"nx": NX, "ny": NY, "x0": X0, "y0": Y0, "step": STEP, "cell_selection": "cells whose 0.25-degree footprints intersect the canonical bbox"},
        "raw_files": [str(raw_path.relative_to(ROOT)).replace("\\", "/"), str(ctl_path.relative_to(ROOT)).replace("\\", "/")],
        "processed_file": str(output_path.relative_to(ROOT)).replace("\\", "/"),
        "study_area": area["bbox"],
        "byte_order_detected": "little-endian" if endian == "<" else "big-endian",
        "record_count": len(rows),
        "limitations": ["This is a coarse daily grid, not street-level rainfall and not radar/QPE.", "The representative coordinate is the source grid-cell center; cells may have centers just outside the study bbox while their footprints intersect it.", "The selected file is a current daily foundation file, not a curated historical flood-event catalogue."],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
