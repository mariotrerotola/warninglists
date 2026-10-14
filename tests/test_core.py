import json

import idna
import pytest

from warninglists import Alert, Index, cli, store
from warninglists.domains import hosts_in_text, normalize_host, registrable_domain
from warninglists.lexical import (
    bounded_levenshtein,
    compact_name,
    default_max_distance,
    is_token_bounded,
    skeleton,
)
from warninglists.sources.base import FetchResult

# --- domains ----------------------------------------------------------------


@pytest.mark.parametrize(
    "value, host",
    [
        ("https://clientzone.dmaeu.com/login?x=1", "clientzone.dmaeu.com"),
        ("WWW.Example-Broker.CO.UK.", "www.example-broker.co.uk"),
        ("ttps://x-trade.com/path", "x-trade.com"),
        ("user@mail.trade-x.io:8443", "mail.trade-x.io"),
        ("https://kapidexnx.", None),
        ("www.virtufinance.come", None),
        ("decreto.crescita", None),
        ("N/A", None),
        ("", None),
    ],
)
def test_normalize_host(value, host):
    assert normalize_host(value) == host


def test_idn_is_stored_as_punycode():
    host = normalize_host("https://bücher-invest.de/")
    assert host == idna.encode("bücher-invest.de").decode() and host.startswith("xn--")


def test_registrable_domain_uses_psl():
    assert registrable_domain("a.b.example.co.uk") == "example.co.uk"
    assert registrable_domain("app.trade-lgquantichft.com") == "trade-lgquantichft.com"


def test_hosts_in_text():
    text = "Il sito https://alfa.com e la pagina www.beta.it; vedi decreto.crescita e x.file"
    assert hosts_in_text(text) == ["alfa.com", "www.beta.it"]


# --- lexical ----------------------------------------------------------------


def test_bounded_levenshtein():
    assert bounded_levenshtein("etoro", "etoro", 1) == 0
    assert bounded_levenshtein("etoro", "vetoro", 1) == 1
    assert bounded_levenshtein("etoro", "etorro", 1) == 1
    assert bounded_levenshtein("etoro", "binance", 2) is None


def test_token_bounded():
    assert is_token_bounded("login-etoro", "etoro")
    assert is_token_bounded("etoro-wallet", "etoro")
    assert not is_token_bounded("myetorotrading", "etoro")
    assert not is_token_bounded("ing-bank", "ing")  # root too short


def test_skeleton_folds_confusables_and_punycode():
    assert skeleton("еtoro") == "etoro"  # Cyrillic "е"
    assert skeleton("et0r0") == "etoro"
    assert skeleton(idna.encode("еtoro").decode()) == "etoro"


def test_default_max_distance():
    assert [default_max_distance("x" * n) for n in (4, 5, 6, 7)] == [0, 1, 1, 2]


def test_compact_name_drops_legal_forms_only():
    assert compact_name("Alfa Capital S.r.l.") == "alfacapital"
    assert compact_name("ALFA CAPITAL LTD") == "alfacapital"
    assert compact_name("Société Générale Group SA") == "societegeneralegroup"


# --- matcher ----------------------------------------------------------------


def alert(source_id, names, urls, kind="unauthorised", source="test", published="2026-01-01"):
    return Alert(
        source=source,
        source_id=source_id,
        authority="Test Authority",
        jurisdiction="Nowhere",
        kind=kind,
        names=names,
        urls=urls,
        source_url=f"https://example.org/{source_id}",
        published=published,
    )


@pytest.fixture()
def index():
    return Index(
        [
            alert("1", ["Goldgcapital"], ["https://goldgcapital.net", "https://my.aipltfrm.com"]),
            alert("2", ["Etoro Clone Ltd"], ["https://etoro-wallet.com"], kind="clone"),
            alert("3", ["Vetoro"], ["vetoro.cc"]),
            alert("4", ["eToro"], []),
            alert("5", ["Alfa Capital S.r.l."], ["alfacapital.it"]),
        ]
    )


def relations(matches):
    return [(m.alert.source_id, m.relation, m.matched_on) for m in matches]


def test_listed_by_host_and_domain(index):
    assert relations(index.check("https://my.aipltfrm.com/x"))[0] == ("1", "listed", "host")
    assert relations(index.check("login.aipltfrm.com"))[0] == ("1", "listed", "domain")


def test_brand_query_returns_similar_not_listed(index):
    got = relations(index.check("etoro.com"))
    assert ("2", "similar", "domain_token") in got
    assert ("3", "similar", "domain_similar") in got
    # a name equal to the domain label is an inference, not a listing
    assert ("4", "similar", "label_name") in got
    assert not [g for g in got if g[1] == "listed"]


def test_exact_only(index):
    assert index.check("etoro.com", similar=False) == []


def test_name_search(index):
    assert relations(index.search_name("ALFA CAPITAL LTD")) == [("5", "listed", "name")]
    assert relations(index.search_name("Goldcapital"))[0] == ("1", "similar", "name_similar")


def test_one_match_per_alert_best_first(index):
    got = index.check("goldgcapital.net")
    assert [m.alert.source_id for m in got].count("1") == 1
    assert got[0].matched_on == "host"


# --- store and CLI ----------------------------------------------------------


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("WARNINGLISTS_HOME", str(tmp_path))
    store.save(
        FetchResult(
            source="consob",
            status="stable",
            origin="test",
            alerts=[
                alert(
                    "2026-10-09:goldgcapital.net",
                    ["Goldgcapital"],
                    ["goldgcapital.net"],
                    kind="blocked",
                    source="consob",
                )
            ],
        )
    )
    return tmp_path


def test_store_roundtrip(cache):
    alerts = store.load_alerts()
    assert len(alerts) == 1 and alerts[0].domains == ["goldgcapital.net"]
    assert store.load_meta()["consob"]["alerts"] == 1


def test_store_refuses_empty_result(cache):
    with pytest.raises(store.EmptyFetchError):
        store.save(FetchResult(source="consob", alerts=[], status="stable", origin="test"))
    assert len(store.load_alerts()) == 1


def test_cli_check_json_and_exit_code(cache, capsys):
    assert cli.main(["check", "goldgcapital.net", "--json", "--exit-code"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["matches"][0]["relation"] == "listed"
    assert cli.main(["check", "unrelated-domain.com", "--exit-code"]) == 0


def test_cli_export_csv(cache, tmp_path):
    out = tmp_path / "out.csv"
    assert cli.main(["export", "--format", "csv", "-o", str(out)]) == 0
    lines = out.read_text().splitlines()
    assert lines[0].startswith("source,source_id") and "goldgcapital.net" in lines[1]


def test_mcp_tools(cache):
    pytest.importorskip("mcp")
    from warninglists import mcp_server

    res = mcp_server.check_domain("https://goldgcapital.net/")
    assert res["listed"][0]["authority"] == "Test Authority"
    assert mcp_server.search_entity("Goldgcapital")["listed"]
    assert "consob" in mcp_server.list_sources()["sources"]
