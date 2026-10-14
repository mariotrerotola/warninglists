"""MCP server (stdio) over the local cache.

Read-only: it never downloads. Populate the cache with ``warninglists fetch``.
Works with the ``mcp`` SDK 1.x (``FastMCP``) and 2.x (``MCPServer``).
"""

from __future__ import annotations

import inspect
from typing import Any

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import __version__, store
from .matcher import Index

INSTRUCTIONS = """\
Look up domains, URLs and entity names in warning lists published by financial
regulators: IOSCO I-SCAN (alerts from IOSCO members), CONSOB website blocking
orders (Italy) and the FCA warnings feed (UK).

Read each match by its relation:
- "listed": the queried host, domain or name appears in a regulator's alert.
- "similar": a listed domain or name resembles the query. Similarity has no
  direction: when the query is a legitimate brand, similar entries are more
  likely clones of that brand than evidence against it.

No match means only that these lists do not contain the query; they are not
complete (I-SCAN is voluntary) and are not a register of authorised firms.
Always cite the authority and source_url of a match.
"""

_index: Index | None = None
_stamp: tuple | None = None


def _get_index() -> Index:
    """Load the cache once, and again when a fetch has replaced it."""
    global _index, _stamp
    files = sorted(store.home().glob("*.jsonl.gz"))
    stamp = tuple((f.name, f.stat().st_mtime_ns) for f in files)
    if _index is None or stamp != _stamp:
        _index, _stamp = store.load_index(), stamp
    return _index


def _empty() -> dict[str, Any]:
    return {"error": "no cached data; run `warninglists fetch` on this machine first"}


def _answer(query: str, matches) -> dict[str, Any]:
    return {
        "query": query,
        "listed": [m.to_dict() for m in matches if m.relation == "listed"],
        "similar": [m.to_dict() for m in matches if m.relation == "similar"],
    }


_kwargs: dict[str, Any] = {"name": "warninglists", "instructions": INSTRUCTIONS}
if "version" in inspect.signature(_Server.__init__).parameters:  # mcp >= 2
    _kwargs["version"] = __version__
server = _Server(**_kwargs)


@server.tool()
def check_domain(domain: str, include_similar: bool = True, limit: int = 20) -> dict[str, Any]:
    """Check a domain or URL against regulator warning lists.

    Returns alerts where the host or registrable domain is listed, and
    (optionally) alerts with look-alike domains.
    """
    index = _get_index()
    if not len(index):
        return _empty()
    try:
        matches = index.check_domain(domain, similar=include_similar, limit=limit)
    except ValueError as e:
        return {"error": str(e)}
    return _answer(domain, matches)


@server.tool()
def search_entity(name: str, include_similar: bool = True, limit: int = 20) -> dict[str, Any]:
    """Search an entity or brand name in regulator warning lists.

    Legal forms (Ltd, LLC, S.r.l., ...) are ignored. Clone warnings may carry
    the name of the genuine firm being impersonated: check the "kind" field.
    """
    index = _get_index()
    if not len(index):
        return _empty()
    return _answer(name, index.search_name(name, similar=include_similar, limit=limit))


@server.tool()
def list_sources() -> dict[str, Any]:
    """Which lists are cached, when they were fetched, and how complete they are."""
    meta = store.load_meta()
    if not meta:
        return _empty()
    return {"version": __version__, "sources": meta, "index": _get_index().stats()}


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
