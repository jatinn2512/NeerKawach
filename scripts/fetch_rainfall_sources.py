"""Fetch the public Open-Meteo and RainViewer rainfall-source inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.rainfall_sources import OpenMeteoClient, RainViewerClient, RainfallSourceError  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("open-meteo", "rainviewer", "all"), default="all")
    parser.add_argument("--forecast-days", type=int, default=3, help="Open-Meteo forecast horizon, 1-16 days")
    args = parser.parse_args()
    settings = get_settings()
    results = {}
    if args.source in {"open-meteo", "all"}:
        if not settings.open_meteo_enabled:
            raise RainfallSourceError("OPEN_METEO_ENABLED is false")
        results["open_meteo"] = OpenMeteoClient(base_url=settings.open_meteo_base_url, timeout_seconds=settings.rainfall_http_timeout_seconds, retries=settings.rainfall_http_retries).fetch(forecast_days=args.forecast_days)
    if args.source in {"rainviewer", "all"}:
        if not settings.rainviewer_enabled:
            raise RainfallSourceError("RAINVIEWER_ENABLED is false")
        results["rainviewer"] = RainViewerClient(base_url=settings.rainviewer_base_url, timeout_seconds=settings.rainfall_http_timeout_seconds, retries=settings.rainfall_http_retries).fetch()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
