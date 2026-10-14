# How the sources were verified — 2026-10-14

What each source offers, how it was checked, and how the CONSOB parser measures its own
completeness. A dated record: it is not updated, later changes go in the changelog.

## Sources

| Question | Check | Result |
|---|---|---|
| Can I-SCAN be downloaded without credentials? | CSV export `?export-to-csv&NCA_ID=46…` from a residential network | 200, `text/csv`, 451,545 bytes. From a datacenter network the same request was observed to return 403 (2026-08-24) |
| Does I-SCAN already contain FCA and CONSOB alerts? | count on the global CSV of 2026-10-12 (47,371 rows) | FCA (`nca_id` 97): 13,796 rows; CONSOB (`nca_id` 46): 697 rows |
| Is the I-SCAN API open? | `IOSCO_I-SCAN_API_Terms_of_Use_Agreement.pdf` | **No**: signed agreement and credentials (sections 5 and 12). The CSV export is used instead |
| Can I-SCAN data be reused? | same document, section 3 | "public information"; attribution and non-distortion required |
| Does the FCA publish a warnings feed? | `https://www.fca.org.uk/news/warnings/rss.xml` | 200 `application/rss+xml`, 20 items (6–12 October 2026), `<warned_type>` and `<warned>` markers in the text. The HTML list page sits behind a bot challenge (403) |
| Do CONSOB blocking orders have a machine-readable source? | `https://www.consob.it/web/area-pubblica/oscuramenti` | No feed. An index page with the full text of the press releases, 20 per page (a larger `delta` is ignored), 15 pages, 19 September 2019 to 9 October 2026 |
| Does each CONSOB release state its counts? | releases of 24 September and 9 October 2026 | "oscuramento di 7 nuovi siti" (number of sites), "Sale, così, a 1838" (running total) |
| Can CONSOB texts be reused? | `consob.it/web/consob/informazioni-legali` | reuse for study, research, information and documentation, citing the source, without altering meaning or completeness |
| Can FCA pages be redistributed? | `fca.org.uk/legal`, conditions 3.2.1–3.2.3 | **No**: saved copies are for personal or internal use only |

Design consequences of these rows:

1. The package ships no dataset: data is downloaded on the user's machine, on request.
2. I-SCAN also accepts a local CSV (`--iosco-file`), because CI runners and datacenter servers
   may get a 403.
3. Every record carries the issuing authority and a `source_url` (attribution, required by IOSCO
   and CONSOB).
4. The FCA test fixture is synthetic.
5. CONSOB and FCA alerts also reach I-SCAN; the direct sources add freshness and, for CONSOB,
   sites I-SCAN does not carry. `warninglists stats` measures the overlap on each cache.

Not verified: whether the CONSOB release format will stay stable. The 2019 format
(`Company (www.domain)`) differs from the 2026 one (`"Name" (sito https://… e relativa pagina
https://…)`); a future change would show up in the completeness check below.

## CONSOB parser: prediction and rule, written before running it on the full archive

Check 1: each release declares N blocked sites. The parser counts URLs in the "sito" role
(excluding those introduced by "pagina/pagine"). A release agrees when the two numbers match.

Check 2: the latest release declares the running total (1,838 on 9 October 2026). The sum of
the sites parsed from all releases is compared with it.

**Prediction**: at least 90% of the releases with a declared N agree; the sum is within ±5% of
the declared total.

**Rule**:

- if both thresholds hold, the CONSOB adapter ships as `stable`;
- otherwise it ships as `experimental`, and `warninglists stats` lists the disagreeing releases
  with both numbers. The parser is not tuned to chase the total: only reading errors identified
  on a specific release are fixed.

Releases without a readable N are left out of the agreement denominator, and counted.

## Result on the full archive (285 releases, 15 pages, retrieved 2026-10-14)

| Step | Agreement | Sites / declared total | Status under the rule |
|---|---|---|---|
| 1. Parenthesis-based parser, first run | 258/269 (95.9%) | 1,784/1,838 (−2.9%) | stable |
| 2. List-item parser plus the fixes below | 261/271 (96.3%) | 1,803/1,838 (−1.9%) | stable |

The prediction held on the first run. Every later fix is tied to a specific release:

- **3 April 2026**: the body contained `<script>`; `window.analytics` and `event.target` pass the
  Public Suffix List (`.analytics` and `.target` are real TLDs). Scripts and styles are stripped
  before parsing.
- **20 March 2025** (8 declared, 0 read): since 2025 the URL sits outside the parentheses
  (`"Name", sito internet https://… (delibera n. …)`). **30 July 2019**: bare URL lines. Hence
  the switch to list-item extraction.
- **9 October 2026**: the name `"Money-Mentor.io"` is itself a host; roles are read only after
  the name.
- **19 March 2026, 5 June 2026, 16 October 2025**: narrative sentences ("Inoltre, la Consob ha
  chiesto alla piattaforma Meta…") that cite sites already listed, or `facebook.com`. Items whose
  "name" is a sentence (more than 12 words, or a narrative opening) are skipped; within a release
  a host already listed does not count twice.
- **15 January 2026** and others: "Oscurati 5 siti" was not read as a declared N (agreement
  denominator from 269 to 271).

Tried and **rejected**: counting registrable domains instead of hosts. The release of
1 October 2026 counts `ambrosiafx.com` and `client.ambrosiafx.com` as one site; the release of
10 September 2026 counts `www.puprime.com` and `it.puprime.com` as two. Neither unit explains
both, so the unit fixed in advance (one host, one site) stays.

Mismatches that come from the releases and remain: `https://kapidexnx.` (3 April 2026) and
`www.virtufinance.come` (9 March 2023) are truncated or wrong URLs in the text;
`warninglists stats` reports them as `rejected_tokens`.
