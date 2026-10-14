"""Command line interface: ``warninglists fetch | check | search | stats | export | mcp``."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence

from . import __version__, store
from .http import FetchError
from .matcher import Index, Match
from .sources import SOURCES, consob, fca, iosco


def _fetch(args: argparse.Namespace) -> int:
    failed = 0
    for name in args.sources or list(SOURCES):
        if name not in SOURCES:
            print(f"unknown source {name!r}; choose from {', '.join(SOURCES)}", file=sys.stderr)
            return 2
        print(f"→ {name}: fetching…", file=sys.stderr)
        try:
            if name == "iosco":
                result = iosco.fetch(file=args.iosco_file)
            elif name == "consob":
                result = consob.fetch(pages=args.consob_pages)
            else:
                result = fca.fetch(file=args.fca_file)
            store.save(result)
        except (FetchError, store.EmptyFetchError, ValueError, OSError) as e:
            failed += 1
            print(f"✗ {name}: {e}", file=sys.stderr)
            if name == "iosco" and isinstance(e, FetchError) and e.status == 403:
                print(
                    "  I-SCAN refuses some datacenter networks. Download the CSV from\n"
                    "  https://www.iosco.org/i-scan/ (Export to CSV) and run\n"
                    "  warninglists fetch iosco --iosco-file <file.csv>",
                    file=sys.stderr,
                )
            continue
        line = f"✓ {name}: {len(result.alerts)} alerts, status {result.status}"
        if name == "consob":
            c = result.checks
            line += (
                f" | releases agreeing with their declared count {c['agreement']},"
                f" sites parsed vs declared total {c['sites_vs_total']}"
            )
        print(line, file=sys.stderr)
    return 1 if failed else 0


def _need_index(sources: list[str] | None = None) -> Index:
    index = store.load_index(sources)
    if not len(index):
        print("no cached data: run `warninglists fetch` first", file=sys.stderr)
        sys.exit(2)
    return index


def _print_matches(query: str, matches: list[Match], as_json: bool, full: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {"query": query, "matches": [m.to_dict(full=full) for m in matches]},
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    listed = [m for m in matches if m.relation == "listed"]
    similar = [m for m in matches if m.relation == "similar"]
    print(f"{query}: {len(listed)} listed, {len(similar)} similar")
    for title, group in (("LISTED", listed), ("SIMILAR", similar)):
        if not group:
            continue
        print(f"\n{title}")
        if title == "SIMILAR":
            print("  similarity has no direction: a listed look-alike may be a clone of the query")
        for m in group:
            a = m.alert
            names = "; ".join(a.names[:3]) or "-"
            dist = f" d={m.distance}" if m.distance else ""
            print(
                f"  [{a.source}] {a.authority} ({a.jurisdiction}) · {a.kind} · "
                f"{a.published or 'n/d'}\n"
                f"    {m.matched_on}{dist}: {m.value} · {names}\n"
                f"    {a.source_url}"
            )


def _check(args: argparse.Namespace) -> int:
    index = _need_index(args.source)
    any_listed = False
    for query in args.queries:
        try:
            matches = index.check(query, similar=not args.exact, limit=args.limit)
        except ValueError as e:
            print(f"✗ {e}", file=sys.stderr)
            continue
        any_listed |= any(m.relation == "listed" for m in matches)
        _print_matches(query, matches, args.json, args.full)
    return 1 if (args.exit_code and any_listed) else 0


def _search(args: argparse.Namespace) -> int:
    index = _need_index(args.source)
    matches = index.search_name(args.name, similar=not args.exact, limit=args.limit)
    _print_matches(args.name, matches, args.json, args.full)
    return 0


def overlap(index: Index, a: str, b: str) -> str:
    """Registrable domains of source ``a`` that also appear in source ``b``, as x/y."""
    da = {d for al in index.alerts if al.source == a for d in al.domains}
    db = {d for al in index.alerts if al.source == b for d in al.domains}
    return f"{len(da & db)}/{len(da)}" if da else "n/d"


def _stats(args: argparse.Namespace) -> int:
    meta = store.load_meta()
    index = store.load_index()
    out = {"cache": str(store.home()), "sources": meta, "index": index.stats()}
    present = set(meta)
    if {"consob", "iosco"} <= present:
        out["consob_domains_also_in_iosco"] = overlap(index, "consob", "iosco")
    if {"fca", "iosco"} <= present:
        out["fca_feed_domains_also_in_iosco"] = overlap(index, "fca", "iosco")
    if not args.verbose:
        for m in out["sources"].values():
            if isinstance(m.get("checks"), dict) and "mismatches" in m["checks"]:
                m["checks"]["mismatches"] = len(m["checks"]["mismatches"])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def _export(args: argparse.Namespace) -> int:
    alerts = store.load_alerts(args.source)
    fh = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout
    try:
        if args.format == "jsonl":
            for a in alerts:
                fh.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")
        else:
            w = csv.writer(fh)
            w.writerow(
                [
                    "source",
                    "source_id",
                    "authority",
                    "jurisdiction",
                    "kind",
                    "published",
                    "names",
                    "domains",
                    "hosts",
                    "emails",
                    "source_url",
                ]
            )
            for a in alerts:
                w.writerow(
                    [
                        a.source,
                        a.source_id,
                        a.authority,
                        a.jurisdiction,
                        a.kind,
                        a.published or "",
                        "|".join(a.names),
                        "|".join(a.domains),
                        "|".join(a.hosts),
                        "|".join(a.emails),
                        a.source_url,
                    ]
                )
    finally:
        if args.output:
            fh.close()
    return 0


def _mcp(args: argparse.Namespace) -> int:
    try:
        from .mcp_server import main as mcp_main
    except ImportError:
        print("the MCP server needs the extra: pip install 'warninglists[mcp]'", file=sys.stderr)
        return 2
    mcp_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="warninglists",
        description="Regulator warning lists (IOSCO I-SCAN, CONSOB, FCA) in one schema.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="download the lists into the local cache")
    f.add_argument("sources", nargs="*", help=f"any of: {', '.join(SOURCES)} (default: all)")
    f.add_argument("--iosco-file", help="read a CSV exported from I-SCAN instead of downloading")
    f.add_argument("--fca-file", help="read a saved FCA RSS file instead of downloading")
    f.add_argument(
        "--consob-pages", type=int, help="only the first N index pages (20 releases each)"
    )
    f.set_defaults(func=_fetch)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--source",
            action="append",
            choices=list(SOURCES),
            help="restrict to a source (repeatable)",
        )
        sp.add_argument("--exact", action="store_true", help="listed matches only, no similarity")
        sp.add_argument("--limit", type=int, default=50)
        sp.add_argument("--json", action="store_true")
        sp.add_argument("--full", action="store_true", help="with --json, include the whole alert")

    c = sub.add_parser("check", help="check domains or URLs (or names) against the lists")
    c.add_argument("queries", nargs="+")
    c.add_argument("--exit-code", action="store_true", help="exit 1 if anything is listed")
    common(c)
    c.set_defaults(func=_check)

    s = sub.add_parser("search", help="search an entity name")
    s.add_argument("name")
    common(s)
    s.set_defaults(func=_search)

    st = sub.add_parser("stats", help="cache contents, completeness checks, overlaps")
    st.add_argument("-v", "--verbose", action="store_true", help="list every CONSOB mismatch")
    st.set_defaults(func=_stats)

    e = sub.add_parser("export", help="dump the cached alerts")
    e.add_argument("--format", choices=["jsonl", "csv"], default="jsonl")
    e.add_argument("-o", "--output")
    e.add_argument("--source", action="append", choices=list(SOURCES))
    e.set_defaults(func=_export)

    m = sub.add_parser("mcp", help="run the MCP server on stdio")
    m.set_defaults(func=_mcp)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
