"""Validate a normalized rainfall CSV without changing scientific products.

Example:
  python scripts/ingest_rainfall.py input.csv --source mosdac_insat3dr
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rainfall.contracts import RainfallValidationError, read_normalized_csv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        records = read_normalized_csv(args.input, source=args.source)
    except RainfallValidationError as exc:
        parser.error(str(exc))
    payload = {"source": args.source, "record_count": len(records), "records": [record.as_dict() for record in records]}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
