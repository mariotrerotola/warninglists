"""IOSCO I-SCAN: alerts submitted by IOSCO members, public CSV export.

I-SCAN is voluntary: members decide what to submit, and IOSCO states it does
not verify the content. The API needs a signed agreement and credentials;
this adapter uses the public CSV export instead.

From datacenter networks (CI runners, cloud VMs) the export has been seen to
answer 403. In that case download the CSV from a browser and pass the file.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from ..http import FetchError, get
from ..schema import Alert
from .base import FetchResult

NAME = "iosco"
EXPORT_URL = (
    "https://www.iosco.org/i-scan/?export-to-csv&ValidationDateStart=&NCA_ID={nca}"
    "&CATEGORYID=&ID=&PRODUCTID=&SUBSECTION=main&ValidationDateEnd=&Keywords=&PAGE=1"
)
REQUIRED_COLUMNS = {"id", "nca_name", "commercial_name", "url", "validation_date"}

_CLONE = {"Registered/Licensed entity impersonators"}
_UNAUTHORISED = {"Unregistered/Unlicensed entity offering financial products or services"}


def _split(value: str, pattern: str) -> list[str]:
    return [p.strip() for p in re.split(pattern, value or "") if p.strip()]


def _kind(categories: list[str]) -> str:
    if _CLONE.intersection(categories):
        return "clone"
    if _UNAUTHORISED.intersection(categories):
        return "unauthorised"
    return "other"


def parse_csv(text: str) -> list[Alert]:
    """Parse the I-SCAN CSV export (UTF-8, BOM, CR inside quoted fields)."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿"), newline=""))
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"not an I-SCAN export: missing columns {sorted(missing)}")
    alerts = []
    for row in reader:
        categories = _split(row.get("categories_detailed", ""), r"\|")
        names = [row["commercial_name"]]
        names += _split(row.get("other_commercial_names", ""), r"\|")
        names += _split(row.get("corporate_names", ""), r"\|")
        urls = [row.get("url", ""), row.get("domain_name", ""), row.get("fqdn", "")]
        urls += _split(row.get("other_urls", ""), r"[|,;\s]+")
        alerts.append(
            Alert(
                source=NAME,
                source_id=row["id"],
                authority=row["nca_name"],
                jurisdiction=row.get("nca_jurisdiction", ""),
                kind=_kind(categories),
                names=names,
                urls=urls,
                emails=_split(row.get("email", ""), r"[|,;\s]+"),
                published=row.get("validation_date") or None,
                source_url=row.get("nca_url") or "https://www.iosco.org/i-scan/",
                details={
                    "nca_id": row.get("nca_id"),
                    "categories": categories,
                    "products": _split(row.get("products_detailed", ""), r"\|"),
                    "lei": row.get("lei") or None,
                    "modified": row.get("modification_date") or None,
                    "additional_information": row.get("additional_information") or None,
                },
            )
        )
    return alerts


def fetch(*, file: str | Path | None = None, nca_id: str = "") -> FetchResult:
    """Download the export (all members, or one ``nca_id``) or read a local file."""
    if file:
        text = Path(file).read_text(encoding="utf-8-sig")
        origin = str(file)
    else:
        origin = EXPORT_URL.format(nca=nca_id)
        body = get(origin, timeout=180)
        text = body.decode("utf-8-sig", "replace")
        if "validation_date" not in text[:4096]:
            # A WAF challenge page served with HTTP 200 would otherwise be
            # parsed as an empty list and silently replace the cache.
            raise FetchError(origin, 200, body, "response is not the I-SCAN CSV")
    alerts = parse_csv(text)
    dates = [a.published for a in alerts if a.published]
    checks = {
        "latest_validation_date": max(dates) if dates else None,
        "alerts_without_domain": f"{sum(1 for a in alerts if not a.domains)}/{len(alerts)}",
        "coverage": "voluntary submissions by IOSCO members; not a complete list",
    }
    return FetchResult(source=NAME, alerts=alerts, status="stable", origin=origin, checks=checks)
