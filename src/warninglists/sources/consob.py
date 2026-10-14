"""CONSOB website blocking orders ("oscuramenti", art. 7-octies TUF).

Since July 2019 CONSOB can order Italian internet providers to block websites
offering financial services without authorisation. There is no feed: the
index page publishes the full text of every press release, 20 per page.

Each release names the entity and its websites, e.g.
``"Goldgcapital" (sito https://goldgcapital.net e relativa pagina https://my.x.com)``.
CONSOB counts the "sito" URLs, not the "pagina" ones, and every release
states both how many sites it blocks and the running total. The parser uses
those two numbers to measure its own completeness: see ``FetchResult.checks``.
"""

from __future__ import annotations

import html
import re
import time
from pathlib import Path

from ..domains import hosts_in_text, registrable_domain
from ..http import get
from ..schema import Alert
from .base import FetchResult

NAME = "consob"
BASE = "https://www.consob.it"
INDEX_URL = BASE + "/web/area-pubblica/oscuramenti"
_PORTLET = "com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_m9PTOY4SM1GU"
PAGE_URL = (
    INDEX_URL + f"?p_p_id={_PORTLET}&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
    f"&_{_PORTLET}_delta=20&p_r_p_resetCur=false&_{_PORTLET}_cur={{page}}"
)
MAX_PAGES = 60  # 15 pages in October 2026; a hard stop if the site loops

_MONTHS = {
    m: i
    for i, m in enumerate(
        "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre "
        "novembre dicembre".split(),
        1,
    )
}
_HEADER = re.compile(r"<h4>\s*<strong>\s*(Comunicat\w+ [^<]*?)\s*</strong>\s*</h4>", re.I)
_DATE = re.compile(r"(\d{1,2})\s*(?:°|º)?\s+([a-z]+)\s+(\d{4})", re.I)
_SCRIPTS = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
_BLOCK_TAGS = re.compile(r"</?(?:li|p|br|div|h\d|ul|ol|tr|td|table)\b[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_DECLARED = re.compile(
    r"oscura(?:mento|ti|to)?\s+(?:di\s+)?(?:ulteriori\s+|altri\s+)?(\d+)\s+(?:nuovi\s+|ulteriori\s+)?sit",
    re.I,
)
_TOTAL = re.compile(r"Sale,?\s*(?:così,?\s*)?a\s*(\d[\d.]*)", re.I)
_MAX_NAME_WORDS = 12
_NARRATIVE = re.compile(
    r"\s*(?:-\s*)?(?:in particolare|inoltre|nello specifico|si tratta|tra questi|di seguito|"
    r"la consob|consob|l['’]autorit[àa]|gli interventi|è stat[ao])\b",
    re.I,
)
_ITEM_SPLIT = re.compile(r"[\n;]")
_NAME_STOP = re.compile(r"\(|,?\s*\b(?:sit[oi]|domini?o?|pagin[ae])\b|https?:/|www\.", re.I)
_EXCLUDED = {"consob.it"}


def _italian_date(text: str) -> str | None:
    m = _DATE.search(text)
    if not m or m.group(2).lower() not in _MONTHS:
        return None
    return f"{int(m.group(3)):04d}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def _to_text(fragment: str) -> str:
    text = _BLOCK_TAGS.sub("\n", fragment)
    text = html.unescape(_TAGS.sub("", text)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def _roles(group: str, rejected: list[str]) -> tuple[list[str], list[str]]:
    """Split the URLs of one parenthesis into (sites, pages).

    URL-looking tokens that fail the PSL go to ``rejected``: a typo in the
    release ("https://kapidexnx.") must show up in the checks, not vanish.
    """
    sites, pages = [], []
    role = "site"
    for token in re.split(r"[\s,;]+", group):
        low = token.lower().strip("\"'.:()“”«»")
        if low.startswith(("pagin", "page")):
            role = "page"
            continue
        if low in ("sito", "siti", "site", "sites", "dominio", "domini"):
            role = "site"
            continue
        hosts = hosts_in_text(token)
        if not hosts and re.match(r"(?:https?:/|www\.)", low):
            rejected.append(token)
        for host in hosts:
            if registrable_domain(host) in _EXCLUDED:
                continue
            (sites if role == "site" else pages).append(host)
    return sites, pages


def site_count(entry: dict) -> int:
    """Sites in "sito" role, counted per host.

    CONSOB's own unit is not consistent: on 10 September 2026 www.puprime.com
    and it.puprime.com count as two sites, on 1 October 2026 ambrosiafx.com
    and client.ambrosiafx.com count as one. Neither unit explains both, so the
    rule fixed before looking at the archive (one host, one site) stays.
    """
    return len(entry["sites"])


def _clean_name(raw: str) -> str:
    name = raw.strip().strip("-–•*").strip()
    name = re.sub(r"^(?:e|ed|nonché|and)\s+", "", name, flags=re.I)
    return name.strip(" \"'“”«»:;,.-").strip()


def _names(raw: str) -> list[str]:
    """'"Rocketprobit" – "flintmoor.buzz"' -> two names; unquoted text -> one."""
    quoted = [a or b for a, b in re.findall(r'"([^"]+)"|“([^”]+)”', raw)]
    quoted = [q.strip() for q in quoted if q.strip()]
    if quoted:
        return quoted
    name = _clean_name(raw)
    if not name:
        return []
    # "Bauman Ltd e Pacific Consulting Co Ltd": two entities in one order.
    parts = [_clean_name(p) for p in re.split(r"\s+(?:e|ed)\s+|,\s+", name)]
    if len(parts) > 1 and all(p and (p[0].isupper() or p[0].isdigit()) for p in parts):
        return [name] + parts
    return [name]


def _entries(text: str, rejected: list[str]) -> list[dict]:
    """One entry per list item (line or ";"-separated) that contains a host.

    Covers the three formats seen 2019-2026:
    ``Società (www.x.com)``, ``"Nome" (sito https://x e relativa pagina https://y)``,
    ``"Nome", sito internet https://x (delibera n. ...)``, and bare URL lines.
    """
    entries: list[dict] = []
    listed: set[str] = set()  # hosts already listed in this release
    pending: list[str] = []  # short host-less lines: a name split over lines
    for item in _ITEM_SPLIT.split(text):
        item = item.strip()
        if not item:
            continue
        # Roles are read after the name only: a name such as "Money-Mentor.io"
        # is itself a host and is not a blocked site of its own.
        stop = _NAME_STOP.search(item)
        head, tail = (item[: stop.start()], item[stop.start() :]) if stop else ("", item)
        if len(head.split()) > _MAX_NAME_WORDS or _NARRATIVE.match(head):
            # A sentence, not a name: narrative that cites hosts already listed
            # ("Inoltre, la Consob ha chiesto alla piattaforma Meta ...").
            pending = []
            continue
        sites, pages = _roles(tail, rejected)
        sites = [h for h in dict.fromkeys(sites) if h not in listed]
        pages = [p for p in dict.fromkeys(pages) if p not in sites and p not in listed]
        if not sites and not pages:
            pending = (pending + [item])[-3:] if len(item) <= 80 and not item.endswith(":") else []
            continue
        listed.update(sites, pages)
        names = _names(head) or _names(" ".join(pending))
        entries.append({"names": names, "sites": sites, "pages": pages})
        pending = []
    return entries


def parse_release(header: str, body_html: str) -> dict:
    """One press release -> date, declared counts and the blocked entities."""
    body_html = _SCRIPTS.sub("", body_html)
    text = _to_text(body_html)
    flat = re.sub(r"\s+", " ", text)
    pdf = re.search(r'href="(/documents/[^"?]+)', body_html)
    rejected: list[str] = []
    entries = _entries(text, rejected)
    declared = _DECLARED.search(flat)
    total = _TOTAL.search(flat)
    title = text.split("\n", 1)[0] if text else ""
    return {
        "header": header,
        "date": _italian_date(header),
        "title": title,
        "declared_sites": int(declared.group(1)) if declared else None,
        "running_total": int(total.group(1).replace(".", "")) if total else None,
        "pdf_url": BASE + pdf.group(1) if pdf else None,
        "entries": entries,
        "rejected_tokens": rejected,
    }


def parse_index_page(page_html: str) -> list[dict]:
    headers = list(_HEADER.finditer(page_html))
    releases = []
    for i, h in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(page_html)
        body = page_html[h.end() : end]
        if i + 1 == len(headers):
            nav_end = body.find("</nav>")
            body = body[:nav_end] if nav_end != -1 else body
        releases.append(parse_release(html.unescape(h.group(1)), body))
    return releases


def releases_to_alerts(releases: list[dict]) -> list[Alert]:
    alerts = []
    for rel in releases:
        for entry in rel["entries"]:
            anchor = (entry["sites"] or entry["pages"])[0]
            alerts.append(
                Alert(
                    source=NAME,
                    source_id=f"{rel['date']}:{anchor}",
                    authority="CONSOB",
                    jurisdiction="Italy",
                    kind="blocked",
                    names=entry["names"],
                    urls=entry["sites"] + entry["pages"],
                    published=rel["date"],
                    source_url=rel["pdf_url"] or INDEX_URL,
                    details={
                        "sites": entry["sites"],
                        "pages": entry["pages"],
                        "release": rel["header"],
                    },
                )
            )
    return alerts


def completeness(releases: list[dict]) -> dict:
    """Declared vs parsed site counts. Thresholds: docs/verification.md."""
    with_declared = [r for r in releases if r["declared_sites"] is not None]
    mismatches = []
    for r in with_declared:
        parsed = sum(site_count(e) for e in r["entries"])
        if parsed != r["declared_sites"]:
            mismatches.append(
                {
                    "release": r["header"],
                    "declared": r["declared_sites"],
                    "parsed": parsed,
                    "rejected_tokens": r["rejected_tokens"],
                }
            )
    totals = [(r["date"] or "", r["running_total"]) for r in releases if r["running_total"]]
    latest_total = max(totals)[1] if totals else None
    parsed_sites = sum(site_count(e) for r in releases for e in r["entries"])
    agree = len(with_declared) - len(mismatches)
    return {
        "releases": len(releases),
        "releases_with_declared_count": len(with_declared),
        "releases_without_declared_count": len(releases) - len(with_declared),
        "releases_agreeing": agree,
        "agreement": f"{agree}/{len(with_declared)}",
        "parsed_sites": parsed_sites,
        "declared_running_total": latest_total,
        "sites_vs_total": f"{parsed_sites}/{latest_total}" if latest_total else None,
        "rejected_url_tokens": sum(len(r["rejected_tokens"]) for r in releases),
        "mismatches": mismatches,
    }


def _status(checks: dict) -> str:
    n = checks["releases_with_declared_count"]
    total = checks["declared_running_total"]
    if not n or not total:
        return "experimental"
    agree_ok = checks["releases_agreeing"] / n >= 0.90
    total_ok = abs(checks["parsed_sites"] - total) / total <= 0.05
    return "stable" if agree_ok and total_ok else "experimental"


def fetch(
    *, pages: int | None = None, delay: float = 2.0, files: list[str | Path] | None = None
) -> FetchResult:
    """Walk the index (all pages, or the first ``pages``) or parse saved pages."""
    releases: list[dict] = []
    if files:
        for f in files:
            releases += parse_index_page(Path(f).read_text(encoding="utf-8", errors="replace"))
        origin = ", ".join(map(str, files))
    else:
        origin = INDEX_URL
        limit = min(pages or MAX_PAGES, MAX_PAGES)
        seen: set[str] = set()
        for page in range(1, limit + 1):
            page_releases = parse_index_page(
                get(PAGE_URL.format(page=page)).decode("utf-8", "replace")
            )
            fresh = [r for r in page_releases if r["header"] + r["title"] not in seen]
            if not fresh:
                break
            seen.update(r["header"] + r["title"] for r in fresh)
            releases += fresh
            if page < limit:
                time.sleep(delay)
    checks = completeness(releases)
    partial = bool(pages) and not files
    if partial:
        checks["note"] = "partial walk: running total not comparable"
    status = "experimental" if partial else _status(checks)
    return FetchResult(
        source=NAME,
        alerts=releases_to_alerts(releases),
        status=status,
        origin=origin,
        checks=checks,
    )
