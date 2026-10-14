from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..schema import Alert


@dataclass
class FetchResult:
    """Alerts from one source plus what is known about how complete they are.

    ``checks`` holds completeness measurements the source itself makes
    possible (for CONSOB: declared vs parsed site counts). A missing check
    means "not measurable for this source", never "passed".
    """

    source: str
    alerts: list[Alert]
    status: str  # "stable" | "experimental"
    origin: str  # URL or local file the data came from
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    checks: dict[str, Any] = field(default_factory=dict)

    def meta(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "origin": self.origin,
            "fetched_at": self.fetched_at,
            "alerts": len(self.alerts),
            "checks": self.checks,
        }
