"""Host and registrable-domain handling.

Every domain decision goes through the Public Suffix List (embedded in the
``publicsuffixlist`` package, no network). Unknown TLDs are rejected: free
text from regulator pages contains tokens such as ``file.chat`` or
``decreto.crescita`` that look like hosts and are not, and accepting them
pollutes any index built on top.
"""

from __future__ import annotations

import re
from functools import lru_cache

import idna
from publicsuffixlist import PublicSuffixList

_PSL = PublicSuffixList(accept_unknown=False)

# A host-looking token inside free text: optional scheme (also the broken
# "ttps://" seen in I-SCAN), optional credentials, labels, then a TLD.
# Validation happens afterwards with the PSL, so this pattern is permissive.
_HOST_IN_TEXT = re.compile(
    r"(?:[a-z]{0,6}://)?(?:[^\s/@]+@)?"
    r"((?:[\w-]+\.)+[\w-]{2,})"
    r"(?::\d{1,5})?(?:/[^\s<>\"'()]*)?",
    re.IGNORECASE | re.UNICODE,
)


def _to_ascii(host: str) -> str | None:
    try:
        return idna.encode(host, uts46=True).decode("ascii")
    except idna.IDNAError:
        try:
            return host.encode("idna").decode("ascii")
        except UnicodeError:
            return None


@lru_cache(maxsize=65536)
def normalize_host(value: str) -> str | None:
    """Return the lowercase ASCII (punycode) host of a URL or bare host.

    ``None`` when the value has no registrable domain under the PSL.
    """
    if not value:
        return None
    # First token only: I-SCAN has values such as "https://x.com (CLONE)".
    parts = value.split()
    v = parts[0].strip(".,;:!?\"'()[]<>").lower() if parts else ""
    v = re.sub(r"^[a-z]{0,6}://", "", v)
    v = v.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    v = v.rsplit("@", 1)[-1]
    v = re.sub(r":\d{1,5}$", "", v).strip(".")
    if not v or "." not in v:
        return None
    host = _to_ascii(v) if not v.isascii() else v
    if not host or registrable_domain(host) is None:
        return None
    return host


@lru_cache(maxsize=65536)
def registrable_domain(host: str) -> str | None:
    """eTLD+1 of an ASCII host (``clientzone.dmaeu.com`` -> ``dmaeu.com``)."""
    if not host:
        return None
    return _PSL.privatesuffix(host.lower())


def public_suffix(host: str) -> str | None:
    return _PSL.publicsuffix(host.lower())


def domain_label(domain: str) -> str:
    """The label left of the public suffix (``dmaeu.com`` -> ``dmaeu``)."""
    suffix = public_suffix(domain)
    if not suffix or domain == suffix:
        return domain
    return domain[: -(len(suffix) + 1)]


def hosts_in_text(text: str) -> list[str]:
    """Every PSL-valid host found in free text, in order, deduplicated."""
    seen: dict[str, None] = {}
    for m in _HOST_IN_TEXT.finditer(text or ""):
        host = normalize_host(m.group(1))
        if host:
            seen.setdefault(host, None)
    return list(seen)
