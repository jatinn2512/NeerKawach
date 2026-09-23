"""NASA IMERG local-file adapter; authentication/download is external."""

from pathlib import Path

from .file import LocalFileProvider


class ImergProvider(LocalFileProvider):
    source_id = "imerg"

    def __init__(self, root: Path) -> None:
        super().__init__(self.source_id, root)

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return (".h5", ".hdf5", ".tif", ".tiff", ".nc", ".csv")
