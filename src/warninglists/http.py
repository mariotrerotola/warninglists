"""Minimal HTTP client: stdlib only, honest User-Agent, polite retries."""

from __future__ import annotations

import gzip
import time
import urllib.error
import urllib.request

from . import __version__

USER_AGENT = f"warninglists/{__version__} (+https://pypi.org/project/warninglists/)"


class FetchError(RuntimeError):
    """The source answered with something other than the expected document."""

    def __init__(self, url: str, status: int | None, body: bytes = b"", reason: str = ""):
        self.url = url
        self.status = status
        self.body = body
        snippet = body[:300].decode("utf-8", "replace").strip()
        msg = f"{url}: {reason or f'HTTP {status}'}"
        if snippet:
            msg += f"\n  first bytes of the response: {snippet!r}"
        super().__init__(msg)


def get(url: str, *, timeout: float = 60.0, retries: int = 2, backoff: float = 3.0) -> bytes:
    """GET ``url`` and return the body. Retries only on 5xx and network errors."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept": "*/*"},
    )
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as e:
            body = e.read() or b""
            if e.code < 500:
                raise FetchError(url, e.code, body) from e
            last = FetchError(url, e.code, body)
        except (urllib.error.URLError, TimeoutError) as e:
            last = FetchError(url, None, reason=str(e))
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
    assert last is not None
    raise last
