# Changelog

## 0.1.0 — unreleased

First version.

- Sources: IOSCO I-SCAN (public CSV export, or a local file), CONSOB website blocking orders
  (full archive since July 2019), FCA warnings RSS feed.
- One `Alert` schema; hosts and registrable domains validated against the Public Suffix List.
- Matching by host, registrable domain and entity name (`listed`), and by look-alike domains and
  names (`similar`).
- Completeness checks per source, shown by `warninglists stats`.
- CLI: `fetch`, `check`, `search`, `stats`, `export`, `mcp`.
- MCP server (stdio) with `check_domain`, `search_entity`, `list_sources`; works with the `mcp`
  SDK 1.x and 2.x.
