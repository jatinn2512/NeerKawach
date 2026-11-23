"""Inspect a registered local rainfall series or validate an individual normalized CSV.

Examples:
  python scripts/ingest_rainfall.py --source arg_aws
  python scripts/ingest_rainfall.py input.csv --source my_source
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rainfall.contracts import RainfallSeries, read_normalized_csv
from app.rainfall.providers.imd import ImdStationProvider, daily_metadata_path, read_daily_csv, read_daily_grid
from app.rainfall.providers.mosdac import MosdacProvider
from app.rainfall.registry import load_registry
from app.rainfall_sources import OPEN_METEO_SOURCE, OpenMeteoClient, RainfallSourceError, load_study_area, utc_now
from app.services.rainfall import load_series


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, help="Optional new JSON file; existing files are protected")
    args = parser.parse_args()
    config = load_registry()["sources"].get(args.source)
    path = args.input.resolve() if args.input else None
    try:
        if path is None:
            if config is None:
                parser.error("unregistered source; supply a normalized input CSV")
            series, _ = load_series(args.source, config, utc_now())
            if not series.records:
                parser.error(f"no local observations or forecasts for {args.source}")
        elif args.source == OPEN_METEO_SOURCE:
            raw_dir = ROOT / config["raw_directory"]
            processed_dir = ROOT / config["processed_directory"]
            raw = path if path.suffix == ".json" else raw_dir / (path.stem + ".json")
            csv_file = path if path.suffix == ".csv" else processed_dir / (path.stem + ".csv")
            if not path.is_file() or path.suffix not in {".json", ".csv"}:
                parser.error("expected a local Open-Meteo capture JSON or CSV")
            series = OpenMeteoClient.read_archive([raw] if raw.is_file() else [],
                [csv_file] if csv_file.is_file() else [], ROOT / "data/rainfall/metadata", as_of=utc_now())
        elif args.source == "imd_ncmrwf_gpm_merged_daily" and path.suffix == ".grd":
            series = read_daily_grid(path, path.with_name("imd_gpm_template.ctl"),
                daily_metadata_path(path, ROOT / "data/rainfall/metadata"), load_study_area()["bbox"])
        elif args.source == "imd_ncmrwf_gpm_merged_daily" and path.suffix == ".csv":
            series = read_daily_csv(path, ROOT / "data/rainfall/metadata" / (path.stem + ".json"))
        elif args.source == "mosdac_insat3dr" and path.suffix.lower() in {".tif", ".tiff"}:
            import rasterio
            with rasterio.open(path) as dataset:
                series = RainfallSeries(MosdacProvider.frame(dataset, path, load_study_area()["bbox"],
                                                             config["native_resolution_m"]))
        elif args.source == "arg_aws" and path.match(config["statement_pattern"]):
            series = ImdStationProvider(path.parent).read_statement(path)
        elif args.source == "mosdac_insat3dr" and path.name == config["processed_file_pattern"]:
            series = MosdacProvider(path.parent).read_subset(path, ROOT / config["metadata_file"])
        else:
            series = RainfallSeries(read_normalized_csv(path, source=args.source))
        payload = json.dumps({"source": args.source, "record_count": len(series.records),
                              "missing_labels": series.missing_labels, "captures": series.captures,
                              "records": [r.as_dict() for r in series.records]}, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(payload + "\n")
        else:
            print(payload)
    except (OSError, ValueError, KeyError, RainfallSourceError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
