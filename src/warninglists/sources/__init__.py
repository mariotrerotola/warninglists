"""One module per regulator. Each exposes ``NAME`` and ``fetch(...) -> FetchResult``."""

from . import consob, fca, iosco

SOURCES = {m.NAME: m for m in (iosco, consob, fca)}

__all__ = ["SOURCES", "consob", "fca", "iosco"]
