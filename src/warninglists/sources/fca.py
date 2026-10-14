"""FCA Warning List, through the official warnings RSS feed.

The feed carries only the most recent warnings (about 20 items, roughly a
week). The full list page sits behind a bot challenge, and the FCA's terms
allow saved copies for personal or internal use only, so this adapter does
not try to rebuild the history: older FCA warnings are reachable through
I-SCAN, where the FCA is the largest contributor.

For clone warnings the item also lists the genuine firm being impersonated.
Those details are kept apart in ``details["impersonated_firm"]`` and never
attributed to the clone.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from ..http import FetchError, get
from ..schema import Alert
from .base import FetchResult

NAME = "fca"
FEED_URL = "https://www.fca.org.uk/news/warnings/rss.xml"

_GENUINE_SECTION = re.compile(
    r"FCA (?:authorised|registered) firm details|The correct details are", re.I
)
_TITLE_TAGS = re.compile(r"\s*\((?:new|updated|clone of [^)]*)\)", re.I)


def _field(text: str, label: str) -> list[str]:
    return [m.strip() for m in re.findall(rf"^\s*{label}:\s*(.+)$", text, re.M) if m.strip()]


def _published(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%A, %B %d, %Y - %H:%M", "%A, %B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        return None


def parse_feed(xml_text: str) -> list[Alert]:
    root = ET.fromstring(xml_text)
    alerts = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = html.unescape(item.findtext("description") or "")
        warned_type = (re.search(r"<warned_type>([^<]*)</warned_type>", desc) or [None, ""])[1]

        # Everything after the genuine-firm header describes the real firm.
        cut = _GENUINE_SECTION.search(desc)
        own, genuine = (desc[: cut.start()], desc[cut.end() :]) if cut else (desc, "")

        clean_title = _TITLE_TAGS.sub("", title).strip()
        names = [p.strip() for p in clean_title.split(" / ")] + _field(own, "Name")
        urls = re.findall(r"<warned>([^<]*)</warned>", own) + _field(own, "Website")
        kind = (
            "clone"
            if warned_type.lower() == "clone" or "clone of" in title.lower()
            else ("unauthorised")
        )
        details: dict = {
            "warned_type": warned_type or None,
            "phones": _field(own, "Telephone") + _field(own, "Mobile"),
            "addresses": _field(own, "Address"),
        }
        if genuine:
            details["impersonated_firm"] = {
                "name": next(iter(_field(genuine, "Firm Name")), None),
                "frn": next(iter(_field(genuine, "Firm Reference Number")), None),
            }
        alerts.append(
            Alert(
                source=NAME,
                source_id=(item.findtext("guid") or link.rsplit("/", 1)[-1]).strip(),
                authority="Financial Conduct Authority",
                jurisdiction="United Kingdom",
                kind=kind,
                names=names,
                urls=urls,
                emails=_field(own, "Email"),
                published=_published(item.findtext("pubDate")),
                source_url=link,
                details=details,
            )
        )
    return alerts


def fetch(*, file: str | Path | None = None) -> FetchResult:
    if file:
        text, origin = Path(file).read_text(encoding="utf-8"), str(file)
    else:
        body = get(FEED_URL)
        text, origin = body.decode("utf-8", "replace"), FEED_URL
        if "<rss" not in text[:2048]:
            raise FetchError(FEED_URL, 200, body, "response is not the FCA RSS feed")
    alerts = parse_feed(text)
    return FetchResult(
        source=NAME,
        alerts=alerts,
        status="stable",
        origin=origin,
        checks={
            "feed_window_items": len(alerts),
            "alerts_without_domain": f"{sum(1 for a in alerts if not a.domains)}/{len(alerts)}",
            "history": "recent items only; older FCA warnings are in iosco",
        },
    )
