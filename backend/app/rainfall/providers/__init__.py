"""Rainfall provider adapters. Public clients remain in app.rainfall_sources."""

from .dwr import DwrUnavailableProvider

__all__ = ["DwrUnavailableProvider"]
