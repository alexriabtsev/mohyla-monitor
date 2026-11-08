# Changelog

## [0.5.0] - 2026-11-08
### Features
- «Події» tab (`events.html`): upcoming NaUKMA events from kmaevents.com for the next 60 days,
  grouped by Kyiv day, with type filters, search, place, organiser and «Додати в календар».
- Site navigation is now tabs: Випуск · Події · Архів · RSS.
- Web-search posts (Instagram, Threads, X, LinkedIn) get their real time from the post id
  in the URL; before, a post without a Tavily date was shown with the fetch time.
### Design Rationale
- Events are announcements, not coverage: they stay out of the digest, ranking, seen-URLs
  and RSS, so they can't crowd out news or be dropped as repeats.
- kmaevents.com is a client-side app; its own public API (`/api/events?from=…`, cursor pages)
  is the cleanest source. Links go to the organiser's post (the site has no event pages).
### Notes & Caveats
- On an API outage the page shows the last good snapshot (`data/kmaevents.json`) and says
  when it was fetched; the snapshot is only replaced after a successful fetch.
- The API host (railway.app) is the site's backend, not a documented API; if it moves,
  update `kmaevents.api_url`.

## [0.4.0] - 2026-11-07
### Features
- No repeats across days: a story already shown in the last `repeat_window_days` (7) issues
  is dropped even under a new URL (reposts, Facebook `pfbid` links, Instagram/Telegram copies).
- Same-story check shared by in-issue dedupe and cross-day filtering: same URL, similar title,
  same body, or a title that opens the other post's text (Instagram titles are the post's start).
- Facebook fits the Apify free plan: a monthly budget ledger (`data/facebook_spend.json`)
  spreads what is left evenly over the billing cycle and skips Facebook when it is spent;
  runs only pay for posts newer than the last successful run (ISO `onlyPostsNewerThan`);
  25 key pages and 3 groups, up to 3 posts each.
- Real Apify cost in the log: per-event charges (or rows x price), not just platform usage.
- `relevance_exclude_patterns`: Petro Mohyla's daughters ("Катерина Могилянка") are not the university.
- Schedule: off-peak cron with backups, plus a `skip_if_built` dispatch input for an external
  scheduler (GitHub fired one scheduled run in three days).
### Design Rationale
- Repeats are matched against stored issues, not raw history: only what readers saw matters,
  and the issues are already in the repo.
- Dropped repeats are still marked seen, so the same URL is not re-checked next day.
- The Facebook actors bill per post; logging `usageTotalUsd` showed $0 while every run hit
  its $0.50 cap, and the free $5 ran out in two days.
### Notes & Caveats
- `facebook_cycle_day` must match the Apify billing date; a mismatch only shifts when
  Facebook resumes (Apify itself blocks runs past the free limit).
- A substantially rewritten follow-up (new facts, new headline) is treated as a new story.

## [0.3.0] - 2026-11-05
### Features
- Facebook at scale: one asynchronous Apify run for all public pages (facebook-posts-scraper)
  and one for all public groups (facebook-groups-scraper), started together and long-polled.
- Spend and time caps per run (`facebook_max_items`, `facebook_max_charge_usd`,
  `facebook_timeout_minutes`); a run over budget is aborted and its partial dataset kept.
- Facebook page/group discovery: links in kept items become sources for the next run
  (`data/facebook_discovered.json`), like Telegram channels.
- Facebook items carry `facebook:<page slug>`, so a person's own post matches their profile
  handle and goes through the own-achievement rule.
### Design Rationale
- One run per actor instead of one per page: 100+ sync runs would exceed the 40-min job limit
  and pay the actor start-up cost each time.
- Sources are capped in priority order (config, people's profiles, discovered), so discovery
  can never push curated sources out or raise the bill past the configured cap.
### Notes & Caveats
- Web search moved from Brave to Tavily (`TAVILY_API_KEY`): Brave's dashboard returns 403
  to Ukrainian IPs and requires a $5 prepaid top-up; Tavily's free plan has 1,000 searches/month
  with no card. Queries are now `{query, domains}` (include_domains instead of `site:`).
- Only public pages, public groups and posts marked Public; Meta's terms forbid scraping, the
  risk sits with Apify. The legitimate full-text route is Meta Content Library (researchers).
- Apify input/field names follow the actors' current docs; the first live run is the check.

## [0.2.0] - 2026-11-05
### Features
- Graduate base from archived alumni pages (1995–2018, 8,706 people, 18 cohorts) via
  `python -m mohyla.cli archive`; matched in Mohyla-context news, shown with a cohort chip.
- Classmate edges (same year + faculty) among graduates that appeared in the news.
- Surname-prefix index for name matching: 30x faster with 8.9k people, identical results.
### Design Rationale
- Names of private individuals stay in a private repo read by a deploy key; public files hold
  only opaque ids, so the public repo never republishes the compiled list.
- Public records win over archive ones, matched by label and aliases (legal names, pen names).
### Notes & Caveats
- Archive gaps: 2006–2007 (Flash only), 2009–2010, 2017, 2019+. 2017+ needs another source.
- Archive graduates have prominence 0: matched only when the item already mentions Mohyla.

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
