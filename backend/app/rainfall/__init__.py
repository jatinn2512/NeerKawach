"""Source-agnostic rainfall contracts and provider discovery for P9."""

from .resolver import resolve_quantitative_source, source_status

__all__ = ["resolve_quantitative_source", "source_status"]
