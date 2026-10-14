"""The common record every source is mapped to."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .domains import normalize_host, registrable_domain

# What the regulator says about the entry, in the regulator's own terms
# reduced to a few values. Nothing here is a judgement made by this package.
KINDS = (
    "unauthorised",  # offering services without the required authorisation
    "clone",  # impersonating an authorised firm
    "blocked",  # website access blocked by order of the authority (CONSOB)
    "other",  # any other alert category
)


@dataclass
class Alert:
    """One entry published by a regulator.

    ``hosts`` and ``domains`` are derived from ``urls`` at construction and
    contain only PSL-valid values.
    """

    source: str
    source_id: str
    authority: str
    jurisdiction: str
    kind: str
    names: list[str]
    urls: list[str]
    source_url: str
    published: str | None = None  # ISO date of publication or validation
    emails: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    hosts: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown kind {self.kind!r}")
        self.names = _dedup(n.strip() for n in self.names if n and n.strip())
        self.urls = _dedup(u.strip() for u in self.urls if u and u.strip())
        self.emails = _dedup(e.strip().lower() for e in self.emails if e and "@" in e)
        if not self.hosts:
            self.hosts = _dedup(h for h in map(normalize_host, self.urls) if h)
        if not self.domains:
            self.domains = _dedup(d for d in map(registrable_domain, self.hosts) if d)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Alert:
        return cls(**data)


def _dedup(values) -> list[str]:
    return list(dict.fromkeys(values))
