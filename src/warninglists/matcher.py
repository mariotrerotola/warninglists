"""Match a domain, URL or entity name against the loaded alerts.

Two relations, kept apart on purpose:

``listed``
    the queried host, registrable domain or entity name appears in an alert.

``similar``
    an alert contains a domain or name close to the query (edit distance,
    confusable characters, or the query as a token inside a longer label).
    Similarity has no direction: if you query a legitimate brand, similar
    entries are more likely clones *of* that brand than evidence against it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .domains import domain_label, normalize_host, registrable_domain
from .lexical import (
    COMBO_MIN_ROOT_LEN,
    bounded_levenshtein,
    compact_name,
    default_max_distance,
    is_token_bounded,
    skeleton,
)
from .schema import Alert

_RANK = {
    "host": 0,
    "domain": 1,
    "name": 2,
    "label_name": 3,
    "domain_similar": 4,
    "domain_token": 5,
    "name_similar": 6,
}
_RELATION = {
    "host": "listed",
    "domain": "listed",
    "name": "listed",
    "label_name": "similar",  # domain label equal to a listed name: an inference
    "domain_similar": "similar",
    "domain_token": "similar",
    "name_similar": "similar",
}


@dataclass(frozen=True)
class Match:
    alert: Alert
    matched_on: str  # one of _RANK
    value: str  # the listed value that matched
    distance: int = 0

    @property
    def relation(self) -> str:
        return _RELATION[self.matched_on]

    def to_dict(self, *, full: bool = False) -> dict:
        a = self.alert
        out = {
            "relation": self.relation,
            "matched_on": self.matched_on,
            "value": self.value,
            "distance": self.distance,
            "source": a.source,
            "authority": a.authority,
            "jurisdiction": a.jurisdiction,
            "kind": a.kind,
            "names": a.names,
            "domains": a.domains,
            "published": a.published,
            "source_url": a.source_url,
        }
        if full:
            out["alert"] = a.to_dict()
        return out


class Index:
    def __init__(self, alerts: Iterable[Alert]):
        self.alerts: list[Alert] = list(alerts)
        self._by_host: dict[str, list[int]] = defaultdict(list)
        self._by_domain: dict[str, list[int]] = defaultdict(list)
        self._by_name: dict[str, list[int]] = defaultdict(list)
        # skeleton of the label left of the suffix -> {(domain, alert index)}
        self._labels: dict[str, set[tuple[str, int]]] = defaultdict(set)
        for i, a in enumerate(self.alerts):
            for h in a.hosts:
                self._by_host[h].append(i)
            for d in a.domains:
                self._by_domain[d].append(i)
                self._labels[skeleton(domain_label(d))].add((d, i))
            for n in a.names:
                key = compact_name(n)
                if key:
                    self._by_name[key].append(i)

    def __len__(self) -> int:
        return len(self.alerts)

    # -- public API -------------------------------------------------------

    def check(self, query: str, *, similar: bool = True, limit: int = 50) -> list[Match]:
        """Domain/URL lookup if ``query`` has a valid host, name search otherwise."""
        if normalize_host(query):
            return self.check_domain(query, similar=similar, limit=limit)
        return self.search_name(query, similar=similar, limit=limit)

    def check_domain(self, value: str, *, similar: bool = True, limit: int = 50) -> list[Match]:
        host = normalize_host(value)
        if not host:
            raise ValueError(f"no registrable domain in {value!r}")
        domain = registrable_domain(host) or host
        found: list[Match] = []
        found += [Match(self.alerts[i], "host", host) for i in self._by_host.get(host, [])]
        found += [Match(self.alerts[i], "domain", domain) for i in self._by_domain.get(domain, [])]
        if similar:
            # A domain label equal to a listed name is an inference about the
            # entity, so it belongs with the similar matches.
            key = compact_name(domain_label(domain))
            if len(key) >= COMBO_MIN_ROOT_LEN:
                found += [
                    Match(self.alerts[i], "label_name", _display(self.alerts[i], key))
                    for i in self._by_name.get(key, [])
                ]
            found += self._similar_domains(domain)
        return self._finish(found, limit)

    def search_name(self, name: str, *, similar: bool = True, limit: int = 50) -> list[Match]:
        key = compact_name(name)
        if not key:
            return []
        found = [Match(self.alerts[i], "name", name) for i in self._by_name.get(key, [])]
        if similar and len(key) >= COMBO_MIN_ROOT_LEN:
            max_d = default_max_distance(key)
            for other, ids in self._by_name.items():
                if other == key:
                    continue
                d = bounded_levenshtein(key, other, max_d)
                if d is not None:
                    found += [
                        Match(self.alerts[i], "name_similar", _display(self.alerts[i], other), d)
                        for i in ids
                    ]
        return self._finish(found, limit)

    def stats(self) -> dict:
        by_source: dict[str, int] = defaultdict(int)
        by_kind: dict[str, int] = defaultdict(int)
        for a in self.alerts:
            by_source[a.source] += 1
            by_kind[a.kind] += 1
        return {
            "alerts": len(self.alerts),
            "by_source": dict(by_source),
            "by_kind": dict(by_kind),
            "distinct_hosts": len(self._by_host),
            "distinct_domains": len(self._by_domain),
            "distinct_names": len(self._by_name),
        }

    # -- internals --------------------------------------------------------

    def _similar_domains(self, domain: str) -> list[Match]:
        q = skeleton(domain_label(domain))
        max_d = default_max_distance(q)
        out: list[Match] = []
        for label, members in self._labels.items():
            hit: tuple[str, int] | None = None
            if label == q:
                hit = ("domain_similar", 0)  # same skeleton, different suffix or glyphs
            elif max_d and abs(len(label) - len(q)) <= max_d:
                d = bounded_levenshtein(q, label, max_d)
                if d is not None:
                    hit = ("domain_similar", d)
            if hit is None and (is_token_bounded(label, q) or is_token_bounded(q, label)):
                hit = ("domain_token", 0)
            if hit:
                out += [Match(self.alerts[i], hit[0], d, hit[1]) for d, i in members if d != domain]
        return out

    @staticmethod
    def _finish(found: list[Match], limit: int) -> list[Match]:
        best: dict[int, Match] = {}
        for m in found:
            k = id(m.alert)
            cur = best.get(k)
            if cur is None or (_RANK[m.matched_on], m.distance) < (
                _RANK[cur.matched_on],
                cur.distance,
            ):
                best[k] = m
        # Newest first inside the same rank: two stable sorts.
        ranked = sorted(best.values(), key=lambda m: m.alert.published or "", reverse=True)
        ranked.sort(key=lambda m: (_RANK[m.matched_on], m.distance))
        return ranked[:limit]


def _display(alert: Alert, key: str) -> str:
    for n in alert.names:
        if compact_name(n) == key:
            return n
    return key
