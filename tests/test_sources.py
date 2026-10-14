from pathlib import Path

import pytest

from warninglists.sources import consob, fca, iosco

FIX = Path(__file__).parent / "fixtures"


# --- IOSCO I-SCAN -----------------------------------------------------------


@pytest.fixture(scope="module")
def iscan():
    return iosco.parse_csv((FIX / "iscan_sample.csv").read_text(encoding="utf-8-sig"))


def by_id(alerts, source_id):
    return next(a for a in alerts if a.source_id == source_id)


def test_iscan_reads_every_row_including_multiline_fields(iscan):
    assert len(iscan) == 12


def test_iscan_fca_row(iscan):
    a = by_id(iscan, "57166")
    assert a.authority == "Financial Conduct Authority"
    assert a.jurisdiction == "United Kingdom"
    assert a.kind == "unauthorised"
    assert a.domains == ["auricrypt-sphereton.vip"]
    assert a.source_url.startswith("https://www.fca.org.uk/news/warnings/")


def test_iscan_impersonators_are_clones(iscan):
    clones = [
        a for a in iscan if "Registered/Licensed entity impersonators" in a.details["categories"]
    ]
    assert clones and all(a.kind == "clone" for a in clones)


def test_iscan_consob_rows(iscan):
    rows = [a for a in iscan if a.details["nca_id"] == "46"]
    assert len(rows) == 2
    assert all(a.jurisdiction == "Italy" for a in rows)


def test_iscan_url_with_trailing_note_keeps_the_host(iscan):
    # "https://olympus-capitallimited.com (CLONE)"-style values
    noted = [a for a in iscan if "(CLON" in " ".join(a.urls)]
    assert noted and all(a.domains for a in noted)


def test_iscan_pipe_separated_urls_and_names(iscan):
    multi_url = [a for a in iscan if len(a.hosts) > 3]
    assert multi_url
    multi_name = [a for a in iscan if len(a.names) > 1]
    assert multi_name


def test_iscan_placeholders_are_not_domains(iscan):
    empty = [a for a in iscan if not a.domains]
    assert len(empty) == 2  # one empty row, one "N/A"/"-" placeholder


def test_iscan_rejects_other_csv():
    with pytest.raises(ValueError, match="not an I-SCAN export"):
        iosco.parse_csv("a,b\n1,2\n")


# --- CONSOB -----------------------------------------------------------------


@pytest.fixture(scope="module")
def releases():
    text = (FIX / "consob_index_sample.html").read_text(encoding="utf-8")
    return {r["date"]: r for r in consob.parse_index_page(text)}


def sites(release):
    return [h for e in release["entries"] for h in e["sites"]]


def test_consob_current_format(releases):
    r = releases["2026-10-09"]
    assert r["declared_sites"] == 4
    assert r["running_total"] == 1838
    assert sites(r) == ["goldgcapital.net", "tradoxiumpro.com", "fxpepper.eu", "money-mentor.io"]
    tradoxium = r["entries"][1]
    assert tradoxium["names"] == ["Tradoxium"]
    assert tradoxium["pages"] == ["clientzone.tradoxiumpro.com", "wt.quantivaedge.com"]


def test_consob_name_that_is_a_host_is_not_a_site(releases):
    entry = releases["2026-10-09"]["entries"][3]
    assert entry["names"] == ["Money-Mentor.io"]
    assert entry["sites"] == ["money-mentor.io"]


def test_consob_two_quoted_names(releases):
    names = [e["names"] for e in releases["2026-09-10"]["entries"]]
    assert ["Rocketprobit", "flintmoor.buzz"] in names


def test_consob_url_outside_parentheses_2025(releases):
    r = releases["2025-03-20"]
    assert r["declared_sites"] == 8
    assert "www.monetizeer.top" in sites(r)
    assert sum(len(e["sites"]) for e in r["entries"]) == 8


def test_consob_2019_formats(releases):
    first = releases["2019-07-30"]  # bare URL lines, no names
    assert sites(first) == [
        "www.allglobalmarkets.com",
        "marketsxchange.com",
        "sigmafortrade.com",
        "www.swisscfd.com",
    ]
    oct19 = releases["2019-10-04"]
    pair = next(e for e in oct19["entries"] if "www.avait.investments" in e["sites"])
    assert "Bauman Ltd" in pair["names"] and "Pacific Consulting Co Ltd" in pair["names"]


def test_consob_typo_in_release_is_reported_not_dropped(releases):
    r = releases["2026-04-03"]
    assert r["declared_sites"] == 32
    assert any("kapidexnx" in t for t in r["rejected_tokens"])


def test_consob_unrelated_release_has_no_entries(releases):
    r = releases["2026-02-09"]
    assert r["entries"] == [] and r["declared_sites"] is None


def test_consob_scripts_are_not_hosts():
    body = (
        '<h2>Consob oscura 1 sito</h2><ul><li>"Alfa" (sito https://alfa-trade.com);</li></ul>'
        "<script>if (window.analytics) { window.analytics.track(event.target) }</script>"
    )
    r = consob.parse_release("Comunicato stampa del 3 aprile 2026", body)
    assert sites(r) == ["alfa-trade.com"]


def test_consob_completeness_reports_source_inconsistency(releases):
    checks = consob.completeness(list(releases.values()))
    # 1 Oct 2026 counts ambrosiafx.com + client.ambrosiafx.com as one site;
    # 3 Apr 2026 has a truncated URL. Both stay visible as mismatches.
    flagged = {m["release"] for m in checks["mismatches"]}
    assert "Comunicato stampa del 1 ottobre 2026" in flagged
    assert "Comunicato stampa del 3 aprile 2026" in flagged
    assert checks["releases_without_declared_count"] >= 1


def test_consob_alerts(releases):
    alerts = consob.releases_to_alerts([releases["2026-10-09"]])
    a = alerts[0]
    assert a.kind == "blocked" and a.authority == "CONSOB" and a.published == "2026-10-09"
    assert a.hosts == ["goldgcapital.net", "my.aipltfrm.com"]
    assert a.source_url.startswith("https://www.consob.it/documents/")


# --- FCA --------------------------------------------------------------------


@pytest.fixture(scope="module")
def feed():
    return fca.parse_feed((FIX / "fca_feed_synthetic.xml").read_text(encoding="utf-8"))


def test_fca_unauthorised(feed):
    a = feed[0]
    assert a.kind == "unauthorised"
    assert a.names == ["Zentravolt Markets"]
    assert a.hosts == ["www.zentravolt-markets.com"]
    assert a.emails == ["desk@zentravolt-markets.com"]
    assert a.published == "2026-10-12"
    assert a.source_id == "900001"


def test_fca_clone_keeps_genuine_firm_apart(feed):
    a = feed[1]
    assert a.kind == "clone"
    assert a.domains == ["quorlex-wealth.net"]
    assert a.emails == ["info@quorlex-wealth.net"]
    assert "quorlex-genuine.co.uk" not in a.domains
    assert a.details["impersonated_firm"] == {
        "name": "Quorlex Genuine Advisers Ltd",
        "frn": "999999",
    }
    assert "Quorlex Wealth" in a.names
