"""MOSDAC INSAT-3DR local historical-file adapter."""

from pathlib import Path

from .file import LocalFileProvider


class MosdacProvider(LocalFileProvider):
    source_id = "mosdac_insat3dr"

    def __init__(self, root: Path) -> None:
        super().__init__(self.source_id, root)

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return (".h5", ".hdf5", ".tif", ".tiff", ".csv")
