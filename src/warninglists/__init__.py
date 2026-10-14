"""Regulator warning lists in one schema, with domain and name matching."""

__version__ = "0.1.0"

from .matcher import Index, Match  # noqa: E402
from .schema import Alert  # noqa: E402

__all__ = ["Alert", "Index", "Match", "__version__"]
