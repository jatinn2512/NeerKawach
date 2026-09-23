"""Reserved IMD DWR adapter.

No public historical Bellandur DWR feed was verified, so this provider never
returns fabricated data and fails explicitly until authorized access exists.
"""

from __future__ import annotations


class DwrUnavailableError(RuntimeError):
    pass


class DwrUnavailableProvider:
    source_id = "dwr_qpe"

    def availability(self) -> dict[str, object]:
        return {"source_id": self.source_id, "available": False, "status": "reserved", "reason": "authorized IMD DWR access is not configured"}

    def fetch(self, *args: object, **kwargs: object) -> None:
        raise DwrUnavailableError("IMD DWR/QPE is reserved but unavailable; data is not fabricated")
