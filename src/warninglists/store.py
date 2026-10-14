"""Local cache: one gzipped JSONL file plus one metadata file per source.

Nothing is bundled with the package. Data is fetched on the user's machine
and stays there, as the sources' reuse terms require.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

from .matcher import Index
from .schema import Alert
from .sources.base import FetchResult


class EmptyFetchError(RuntimeError):
    """A fetch returned zero alerts: an empty answer is not an empty list."""


def home() -> Path:
    if env := os.environ.get("WARNINGLISTS_HOME"):
        return Path(env).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "warninglists"


def _paths(source: str, root: Path | None = None) -> tuple[Path, Path]:
    root = root or home()
    return root / f"{source}.jsonl.gz", root / f"{source}.meta.json"


def save(result: FetchResult, *, root: Path | None = None, allow_empty: bool = False) -> Path:
    """Write atomically. Refuses to replace a cache with an empty result."""
    if not result.alerts and not allow_empty:
        raise EmptyFetchError(
            f"{result.source}: the fetch returned no alerts; the previous cache is kept"
        )
    data_path, meta_path = _paths(result.source, root)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = data_path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for alert in result.alerts:
            fh.write(json.dumps(alert.to_dict(), ensure_ascii=False) + "\n")
    tmp.replace(data_path)
    meta_tmp = meta_path.with_suffix(".tmp")
    meta_tmp.write_text(json.dumps(result.meta(), indent=2, ensure_ascii=False), encoding="utf-8")
    meta_tmp.replace(meta_path)
    return data_path


def cached_sources(root: Path | None = None) -> list[str]:
    root = root or home()
    if not root.exists():
        return []
    return sorted(p.name.removesuffix(".jsonl.gz") for p in root.glob("*.jsonl.gz"))


def load_alerts(sources: list[str] | None = None, *, root: Path | None = None) -> list[Alert]:
    alerts: list[Alert] = []
    for source in sources or cached_sources(root):
        data_path, _ = _paths(source, root)
        if not data_path.exists():
            continue
        with gzip.open(data_path, "rt", encoding="utf-8") as fh:
            alerts += [Alert.from_dict(json.loads(line)) for line in fh if line.strip()]
    return alerts


def load_meta(root: Path | None = None) -> dict[str, dict]:
    out = {}
    for source in cached_sources(root):
        _, meta_path = _paths(source, root)
        if meta_path.exists():
            out[source] = json.loads(meta_path.read_text(encoding="utf-8"))
    return out


def load_index(sources: list[str] | None = None, *, root: Path | None = None) -> Index:
    return Index(load_alerts(sources, root=root))
