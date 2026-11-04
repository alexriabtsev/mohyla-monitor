# Changelog

## [0.1.0] - 2026-11-05
### Features
- Daily NaUKMA media digest: official RSS, Google News (uk/en), public Telegram channels;
  optional Bluesky, Facebook (Apify) and LinkedIn/X/Threads via Brave Search.
- People base of public Mohyla figures from Wikidata (P69/P108 = Q1133013) and
  uk.wikipedia categories, with social handles; graph edges by shared employer and co-mention.
- Snowball discovery: news phrases like «випускниця Могилянки Ім'я Прізвище» add candidates,
  promoted to the base after 2 independent mentions.
- Static site in docs/ (GitHub Pages) with archive and RSS; GitHub Actions runs daily.
### Design Rationale
- The alumni archive (alumni.ukma.edu.ua) returns 403 to everyone, so the base starts from
  public figures and grows through the network of mentions instead of a 17k name list.
- Only public figures and public posts; no scraping of private profiles or login-walled networks.
  Networks without an open API are optional, key-gated collectors that degrade to "disabled".
- Heuristic ranking (no LLM) keeps the daily run free and deterministic.
### Notes & Caveats
- Ukrainian name matching uses stems to cover declension; common names need Mohyla context.
- Google News links are redirect URLs; publisher URL is kept in extra when available.
- Hardened after review: every processed URL (incl. folded duplicates) is marked seen;
  a same-day re-run extends the issue; state is saved only after a successful publish;
  people refresh refuses to shrink the base by >30%; snowball promotion needs 2 distinct
  outlets and is announced once; surname matching uses a closed set of case endings.
