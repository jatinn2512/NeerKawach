"""IMD statement and daily merged-grid readers, independent of acquisition."""
from __future__ import annotations

import csv
import json
import math
import re
import struct
from datetime import date, datetime, timedelta
from dataclasses import replace
from pathlib import Path

from app.rainfall.contracts import (NativeGrid, RainfallRecord, RainfallSeries, RainfallValidationError,
                                   read_normalized_csv, validate_records)
from app.rainfall.registry import relative_path
from .file import LocalFileProvider


class ImdDspProvider(LocalFileProvider):
    source_id = "imd_dsp"

    def __init__(self, root: Path) -> None:
        super().__init__(self.source_id, root)


def decode_values(payload: bytes, nx: int = 241, ny: int = 281, endian: str | None = None) -> tuple[str, list[float]]:
    """Decode the original IMD Float32 layout. Use recorded byte order when available."""
    count = nx * ny
    if len(payload) != count * 4 or endian not in (None, "<", ">"):
        raise RainfallValidationError("unexpected IMD grid size or byte order")
    candidates = []
    for order in ([endian] if endian else ["<", ">"]):
        values = list(struct.unpack(f"{order}{count}f", payload))
        plausible = sum(math.isfinite(v) and -999.1 <= v <= 10000 for v in values)
        candidates.append((plausible, order, values))
    _, order, values = max(candidates, key=lambda item: item[0])
    return order, values


def read_control(path: Path, crs: str) -> NativeGrid:
    parts = [line.lower().split() for line in path.read_text().splitlines() if line.strip()]
    directives = {tokens[0]: tokens[1:] for tokens in parts}
    if (directives.get("vars") != ["1"] or "rf" not in directives
            or directives.get("tdef", [])[:2] != ["1", "linear"] or directives["tdef"][-1] != "1dy"
            or "options" in directives or crs != "EPSG:4326"):
        raise RainfallValidationError("unsupported IMD daily control layout")
    def axis(key):
        n, kind, start, step = directives[key]
        if kind != "linear" or int(n) < 1 or float(step) <= 0:
            raise RainfallValidationError(f"unsupported IMD {key}")
        return int(n), float(start), float(step)
    nx, x0, dx = axis("xdef")
    ny, y0, dy = axis("ydef")
    return NativeGrid(crs, nx, ny, x0 - dx / 2, y0 - dy / 2, dx, dy, float(directives["undef"][0]))


def daily_metadata_path(raw: Path, metadata_dir: Path) -> Path:
    day = datetime.strptime(raw.stem, "%d%m%Y").date()
    return metadata_dir / f"imd_gpm_{day}.json"


def read_daily_csv(path: Path, metadata_path: Path) -> RainfallSeries:
    """Read a P1 derivative even in a checkout without the binary. Its precision is recorded."""
    source = "imd_ncmrwf_gpm_merged_daily"
    meta = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    definition = meta.get("grid_definition")
    grid = None
    if definition:
        dx = definition["step"]
        grid = NativeGrid(meta["crs"], definition["nx"], definition["ny"], definition["x0"] - dx/2,
                          definition["y0"] - dx/2, dx, dx, None)
    records = []
    for row in read_normalized_csv(path, source=source):
        day = row.timestamp_utc[:10]
        if meta.get("product_date", day) != day:
            raise RainfallValidationError("IMD CSV and acquisition date disagree")
        geometry = {"kind": "grid_cell", "center": (row.longitude, row.latitude),
                    "crs": meta.get("crs"), "footprint": None}
        if grid:
            col = math.floor((row.longitude - grid.west) / grid.dx)
            index = math.floor((row.latitude - grid.origin_y) / grid.dy)
            geometry = grid.pixel(index, col)
            if geometry["center"] != (row.longitude, row.latitude):
                raise RainfallValidationError("IMD CSV coordinate is not a native pixel centre")
        records.append(replace(row, source_file=relative_path(path), product=source, variable="rf",
            source_record_id=f"{day}/{row.latitude}/{row.longitude}", original_value=row.rainfall_mm,
            original_unit="mm", measurement_type="daily_accumulation", observed=True, geometry=geometry,
            source_label=row.timestamp_utc, reported_date=day, retrieved_at_utc=meta.get("acquired_at_utc"),
            timestamp_convention="assigned product date; midnight UTC is a legacy label; daily cutoff unknown",
            interval_seconds=86400, cadence_seconds=86400,
            provenance={"provider": "IMD/NCMRWF", "value_basis": "rounded processed CSV",
                        "metadata_file": relative_path(metadata_path) if meta else None}))
    return RainfallSeries(records)


def read_daily_grid(raw: Path, control: Path, metadata_path: Path, bbox: dict) -> RainfallSeries:
    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    source = "imd_ncmrwf_gpm_merged_daily"
    product_date = date.fromisoformat(meta["product_date"])
    if raw.stem != product_date.strftime("%d%m%Y"):
        raise RainfallValidationError("IMD assigned product date and raw filename disagree")
    grid = read_control(control, meta["crs"])
    orders = {"little-endian": "<", "big-endian": ">"}
    order, values = decode_values(raw.read_bytes(), grid.width, grid.height, orders[meta["byte_order_detected"]])
    result = []
    for row, col in grid.intersecting_pixels(bbox):
        geometry = grid.pixel(row, col)
        geometry["subset_bbox"] = bbox
        lon, lat = geometry["center"]
        value = values[row * grid.width + col]
        missing = not math.isfinite(value) or value < 0 or value == grid.nodata
        flag = "nodata" if value == grid.nodata else "invalid_source_value"
        rainfall = None if missing else value
        result.append(RainfallRecord(
            f"{product_date}T00:00:00Z", lat, lon, rainfall, source, product=source,
            source_file=relative_path(raw), source_record_id=f"{product_date}/{row}/{col}", variable="rf",
            measurement_type="daily_accumulation", original_value=rainfall, original_unit="mm",
            source_label=meta["product_date"], reported_date=product_date.isoformat(), observed=True,
            timestamp_convention="assigned product date; midnight UTC is a legacy label; daily cutoff unknown",
            cadence_seconds=86400, interval_seconds=86400, retrieved_at_utc=meta["acquired_at_utc"],
            geometry=geometry, spatial_resolution=f"{grid.dx:g} x {grid.dy:g} degrees",
            missing=missing, quality_flags=(flag,) if missing else (),
            provenance={"provider": meta.get("provider"), "control_file": relative_path(control),
                        "metadata_file": relative_path(metadata_path), "byte_order": order},
        ))
    return RainfallSeries(result)


class ImdStationProvider(LocalFileProvider):
    source_id = "arg_aws"

    def __init__(self, root: Path) -> None:
        super().__init__(self.source_id, root)

    def read_statement(self, path: Path) -> RainfallSeries:
        """An IMD statement reports local calendar dates with an unspecified day boundary."""
        metadata = {}
        records = []
        station_ids = set()
        header = ["SL.#", "STATION ID", "DATE", "RAINFALL (MM)"]
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            for cells in reader:
                if [c.strip().upper() for c in cells] == header:
                    break
                if not cells or not any(c.strip() for c in cells):
                    continue
                key, _, value = " ".join(c.strip() for c in cells).partition(":")
                metadata[key.strip().upper()] = value.strip()
            else:
                raise RainfallValidationError("missing IMD station table header or rainfall unit")
            def coordinate(key, directions):
                match = re.fullmatch(r"(\d+(?:\.\d+)?)\s+DEG\.\s*([" + directions + "])", metadata.get(key, ""), re.I)
                if not match:
                    raise RainfallValidationError(f"invalid station {key}")
                return float(match[1]) * (-1 if match[2].upper() in "SW" else 1)
            lat, lon = coordinate("LATITUDE", "NS"), coordinate("LONGITUDE", "EW")
            name = metadata.get("STATION")
            if not name:
                raise RainfallValidationError("missing station name")
            for cells in reader:
                if not cells or cells[0].strip().startswith("0 indicates that rainfall"):
                    continue
                if len(cells) != 4 or not cells[0].strip().isdigit() or not cells[1].strip():
                    raise RainfallValidationError(f"invalid station row at line {reader.line_num}")
                _, station, label, text = (c.strip() for c in cells)
                reported = datetime.strptime(label, "%d-%m-%Y").date().isoformat()
                station_ids.add(station)
                try:
                    value = float(text)
                except ValueError:
                    value = math.nan
                missing = not math.isfinite(value) or value < 0
                amount = None if missing else value
                records.append(RainfallRecord(
                    None, lat, lon, amount, self.source_id, station_id=station, product="imd_arg_daily_statement",
                    source_file=relative_path(path), source_record_id=f"{station}/{reported}", variable="RAINFALL (MM)",
                    measurement_type="daily_accumulation", original_value=amount, original_unit="mm", observed=True,
                    source_label=label, reported_date=reported, cadence_seconds=86400, interval_seconds=86400,
                    timestamp_convention="provider calendar date; timezone and observation-day cutoff unknown",
                    geometry={"kind": "station", "center": (lon, lat), "crs": None, "station_name": name},
                    missing=missing, quality_flags=("invalid_source_value",) if missing else (),
                    provenance={"provider": "IMD", "source_text": text, "coverage": "station point"},
                ))
        if len(station_ids) != 1:
            raise RainfallValidationError("expected one station ID in station statement")
        records = sorted(validate_records(records), key=lambda r: r.reported_date)
        listed = {date.fromisoformat(r.reported_date) for r in records}
        first, last = min(listed), max(listed)
        dates = (first + timedelta(days=i) for i in range((last-first).days + 1))
        return RainfallSeries(records, [d.isoformat() for d in dates if d not in listed])
