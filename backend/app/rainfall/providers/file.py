"""Local-file provider base for historical rainfall products.

It deliberately accepts normalized CSV first. Raster/HDF5 ingestion remains a
provider-specific operation because those formats carry different grids and
metadata; no file is silently flattened into a misleading point series.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.rainfall.contracts import RainfallRecord, read_normalized_csv


class LocalFileProvider:
    def __init__(self, source_id: str, root: Path) -> None:
        self.source_id = source_id
        self.root = root

    def files(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(path for path in self.root.rglob("*") if path.is_file())

    def availability(self) -> dict[str, Any]:
        files = self.files()
        return {"source_id": self.source_id, "available": bool(files), "status": "available" if files else "configured", "files": [path.as_posix() for path in files]}

    def read_csv(self, path: Path, *, bbox: dict[str, float] | None = None) -> list[RainfallRecord]:
        if path.parent != self.root and self.root not in path.parents:
            raise ValueError("rainfall input must remain below the provider root")
        return read_normalized_csv(path, bbox=bbox, source=self.source_id)
