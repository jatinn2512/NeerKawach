"""Local adapters for IMD/DSP and station files."""

from pathlib import Path

from .file import LocalFileProvider


class ImdDspProvider(LocalFileProvider):
    source_id = "imd_dsp"

    def __init__(self, root: Path) -> None:
        super().__init__(self.source_id, root)


class ImdStationProvider(LocalFileProvider):
    source_id = "arg_aws"

    def __init__(self, root: Path) -> None:
        super().__init__(self.source_id, root)
