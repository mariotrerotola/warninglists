# warninglists

Warning lists published by financial regulators, in one schema, with domain and name matching.
A Python library, a command line tool and an MCP server.

| Source | What it is | How it is read |
|---|---|---|
| `iosco` | **IOSCO I-SCAN**: alerts submitted by IOSCO members (FCA, CNMV, AMF, FINMA, SEC, CONSOB, …) | public CSV export |
| `consob` | **CONSOB website blocking orders** (Italy, since July 2019) | full text of the press releases |
| `fca` | **FCA Warning List**, latest items | official warnings RSS feed |

Why three sources when I-SCAN already aggregates regulators: I-SCAN is voluntary and lags.
On 14 October 2026, of the 1,944 registrable domains named in CONSOB blocking orders,
598 were also in I-SCAN; of the 20 domains in that week's FCA feed, 1 was.
`warninglists stats` recomputes both figures on your own cache.

## Install

```bash
pip install warninglists            # library and CLI
pip install "warninglists[mcp]"     # plus the MCP server
```

Python 3.10+. Two dependencies: `publicsuffixlist` and `idna`.

## Command line

```bash
warninglists fetch                          # download all three lists into ~/.cache/warninglists
warninglists check https://clientzone.dmaeu.com/login
warninglists check etoro.com --json
warninglists search "Goldgcapital"
warninglists stats                          # freshness and completeness of each source
warninglists export --format csv -o alerts.csv
```

```text
$ warninglists check https://clientzone.dmaeu.com/login
https://clientzone.dmaeu.com/login: 1 listed, 0 similar

LISTED
  [consob] CONSOB (Italy) · blocked · 2026-09-24
    host: clientzone.dmaeu.com · DMAsseteuBV
    https://www.consob.it/documents/d/area-pubblica/comunicato-stampa-del-24-settembre-2026
```

`check --exit-code` exits with 1 when anything is listed, for use in scripts.

## Python

```python
from warninglists import store
from warninglists.sources import consob, fca, iosco

for source in (iosco, consob, fca):
    store.save(source.fetch())

index = store.load_index()
for match in index.check("tradoxiumpro.com"):
    print(match.relation, match.alert.authority, match.alert.published, match.alert.source_url)
```

## MCP server

The server reads the local cache and never downloads; run `warninglists fetch` first.
It exposes `check_domain`, `search_entity` and `list_sources`.

```json
{
  "mcpServers": {
    "warninglists": { "command": "warninglists", "args": ["mcp"] }
  }
}
```

## Reading a result

Every match has a **relation**:

- **`listed`**: the queried host, registrable domain or entity name appears in an alert.
- **`similar`**: an alert contains a look-alike domain (edit distance, confusable characters,
  the query as a token inside a longer label) or a name equal to the domain's label.
  Similarity has no direction. If you query a legitimate brand, similar entries are more likely
  clones *of* that brand than evidence against it.

Three more things to keep in mind:

- An alert is issued by one authority for its own jurisdiction. A firm licensed in one country
  can be listed by a regulator of another country where it is not authorised; the
  `authority` and `jurisdiction` fields say which.
- No match means these lists do not contain the query. They are not complete, and they are not
  a register of authorised firms.
- Clone warnings concern firms impersonating an authorised one. For FCA clones the genuine
  firm is kept apart in `details["impersonated_firm"]` and never attributed to the clone.

## How complete each source is

Each fetch records what the source makes measurable, in `warninglists stats`:

- **CONSOB.** Every press release states how many sites it blocks and the running total. On the
  full archive (285 releases, 19 September 2019 to 9 October 2026) the parsed site count matches
  the declared count in 261 of 271 releases, and the parsed sites add up to 1,803 against a
  declared total of 1,838. The remaining mismatches are listed one by one; some come from the
  releases themselves (truncated URLs such as `https://kapidexnx.`, and a counting unit that
  differs between releases). The thresholds and every correction made to the parser are in
  [docs/verification.md](docs/verification.md).
- **I-SCAN.** Date of the latest validated alert, and how many alerts carry no domain
  (27,542 of 47,367 on 14 October 2026: those are matchable by name only).
- **FCA.** The feed holds about 20 items, roughly one week. Older FCA warnings are in I-SCAN,
  where the FCA is the largest contributor.

## Data and terms of use

The package contains no data. Lists are downloaded on your machine, when you run `fetch`, and
stay there. Every record keeps the issuing authority and a `source_url`. Before reusing the data,
read each source's terms:

- **IOSCO I-SCAN**: public information; reuse requires attribution and no distortion. The I-SCAN
  API needs a signed agreement; this package uses the public CSV export instead.
- **CONSOB**: reuse for study, research, information and documentation, citing the source and
  without altering meaning or completeness ([informazioni legali](https://www.consob.it/web/consob/informazioni-legali)).
- **FCA**: saved copies are for personal use or use within your organisation, not for
  redistribution ([fca.org.uk/legal](https://www.fca.org.uk/legal)).

The FCA fixture in `tests/` is synthetic for that reason; the I-SCAN and CONSOB fixtures are short
excerpts with attribution ([tests/fixtures/NOTICE.md](tests/fixtures/NOTICE.md)).

From datacenter networks (CI runners, cloud VMs) the I-SCAN export has been seen to answer 403.
Download the CSV from https://www.iosco.org/i-scan/ ("Export to CSV") and run
`warninglists fetch iosco --iosco-file <file.csv>`. Requests identify themselves as
`warninglists/<version>`; CONSOB pages are fetched two seconds apart.

## Schema

```python
Alert(
    source="consob",                 # iosco | consob | fca
    source_id="2026-10-09:goldgcapital.net",
    authority="CONSOB",              # for iosco: the member that submitted the alert
    jurisdiction="Italy",
    kind="blocked",                  # unauthorised | clone | blocked | other
    names=["Goldgcapital"],
    urls=["goldgcapital.net", "my.aipltfrm.com"],
    hosts=[...], domains=[...],      # derived; only values valid under the Public Suffix List
    emails=[...],
    published="2026-10-09",
    source_url="https://www.consob.it/documents/d/area-pubblica/comunicato-stampa-del-9-ottobre-2026",
    details={...},                   # source-specific: sites vs pages, categories, impersonated firm
)
```

Domains are handled with the Public Suffix List only: unknown TLDs are rejected, so tokens such as
`decreto.crescita` in free text never become domains. Two traps remain that the PSL cannot see,
because `.analytics` and `.target` are real TLDs: script code is stripped from pages before parsing.

## License

MIT for the code. The data belongs to the issuing authorities and follows their terms.
