# Plan: Hydrograf as a public service: the regulamin, the request limit, logs, statistics and the form

Approved: 2026-11-13, the author's order in session (one regulamin for every public GUI of
the ecosystem and the rules that make its text true), as step 3 of Nogat's plan
`docs/plans/2026-11-13-gui-terms.md` (Nogat `develop` `2b513d0`, DEV-15.7 to DEV-15.12,
DEV-18.1, ECO-061 to ECO-063); the details by delegated authority, decided in ADR-084.

Requirements: Nogat DEV-15.7 (the kit's regulamin filled from `[nogat.operator]`, the link
in every view and the menu's `terms`), DEV-15.8 (the statement), DEV-15.9 (300 requests in
60 s per client address, static files not counted, 429 with `Retry-After`, a Polish page or
the problem `rate_limited`, the address in memory only), DEV-15.10 (no client address in any
log, logs deleted after 14 days), DEV-15.11 (daily totals only, visitors by a salted HMAC),
DEV-15.12 („Zgłoś uwagę” with the text and the view's context, no contact field), DEV-18.1
(the tables `operator` and `gui` of `nogat.toml`), DEV-15.6 (the kit 0.4.0 copied byte for
byte).

## Goal

Anyone uses Hydrograf without signing in, under the regulamin of the ecosystem filled for
the deployment, and the service keeps no personal data the regulamin does not name: the
client's address lives only in the API's memory (the window of its limit and the day's
salted hash), no log names it, the logs are gone after 14 days, the statistics are daily
totals, and a report holds its text and the view's context. Without `[nogat.operator]` (a
local run) there is no regulamin, no footer, no menu entry and no e-mail under the form.

## Audit (2026-11-13, `develop` `12b2a7e`, before this plan)

| Rule | Before | Change |
|---|---|---|
| Regulamin (DEV-15.7, DEV-15.8) | none | `core/terms.py` fills the kit's `nogat-terms.html` at `/regulamin.html`; `GET /api/terms`; the footer of the map and the guide (`js/terms.js`); the menu's `terms` |
| Limit (DEV-15.9) | nginx `limit_req` keyed by `$binary_remote_addr`, the tunnel connector's address: one bucket for every client; nginx's HTML 429 | the app (`api/traffic.py`, `core/request_limit.py`): 300 in 60 s per address from `CF-Connecting-IP`, tiles ten times that, the form 5 in 5 minutes; the Polish page or `rate_limited` |
| Logs (DEV-15.10) | nginx wrote `$remote_addr`, `$remote_user`, the referrer; the error log at `error` with `client:`; uvicorn's access log; json-file up to 500 MiB per container | nginx's access line without the client, the error log at `crit`, `--no-access-log`; journald with `docker/journald.conf`, at most 14 days |
| Statistics (DEV-15.11) | none; nginx served the pages | pages pass through the API (`X-Accel-Redirect`); `core/usage.py` writes `<data_dir>/hydrograf/stats.jsonl` |
| Form (DEV-15.12) | optional contact, page URL, opt-in diagnostics (`js/diagnostics.js`), the User-Agent stored | `{message, context}`; migration 007 adds `context`, the old columns stay with the old reports |
| Admin | `/admin`, `/api/admin/*` with `X-Admin-Key` | the same, behind Cloudflare Access; the list gives `context` and `legacy` |

## Steps

1. The kit 0.4.0 copied into `frontend/nogat/` (with `nogat-terms.html`, `.css`, `.md`). Done.
2. `core/terms.py`, `api/endpoints/site.py`: the regulamin from NOGAT_CONFIG and the table
   `gui` (HYDROGRAF_GUI, else `[nogat] gui` of that file), `/regulamin.html`,
   `GET /api/terms`; the pages answered with `X-Accel-Redirect`. Done.
3. `api/traffic.py`, `core/request_limit.py`, `core/usage.py`: the middleware of the limit
   and the totals, `POST /api/downloads`, the problem `rate_limited` and the Polish page.
   Done.
4. nginx (`docker/nginx.conf`, `docker/nginx-ssl.conf.template`): no `limit_req`, the access
   line without the client, the error log at `crit`, the pages to the API with the file as
   fallback. Compose: NOGAT_CONFIG mounted at `/config/nogat.toml`, the kit at
   `/frontend/nogat`, journald for nginx and the API, one uvicorn process,
   `--no-access-log`; `docker/journald.conf`. Done.
5. The form: `{message, context}`, migration 007, the admin list with `context` and
   `legacy`; `js/diagnostics.js` removed; the DEV-15.12 line. Done.
6. The front end: the footer (`js/terms.js`), the menu's `terms`, `POST /api/downloads`
   for each saved file (hietogram CSV and JSON, PMAXTP GeoJSON, hand-off file). Done.
7. Documents: ADR-084, DECISIONS, README, CHANGELOG, PROGRESS, CLAUDE, ARCHITECTURE,
   DATA_MODEL, SCOPE. Done.

## Verification

- Unit tests: the regulamin's filling and its absence without an operator
  (`tests/unit/test_terms.py`), the fixed window and its forgetting
  (`tests/unit/test_request_limit.py`), the totals, the salt and the daily file
  (`tests/unit/test_usage.py`), the GUI table from NOGAT_CONFIG (`tests/unit/test_gui.py`),
  the admin list (`tests/unit/test_admin_feedback.py`), the catalogue
  (`tests/contract/test_messages.py`).
- Integration tests: the pages and `/api/terms` (`tests/integration/test_site.py`), the
  limits, the 429 page and problem, the client address through private hops only, the
  logs without the client (`tests/integration/test_traffic.py`), the form refusing any
  other member and storing no User-Agent (`tests/integration/test_feedback.py`).
- A throwaway stack of the branch on one origin, port 18094 (not a deployed instance),
  with Chromium: the regulamin filled from a test `nogat.toml`, the footer under the map and
  in the guide, the menu's „Regulamin”, a report stored with its context and without a
  contact, the Polish 429 page and the problem `rate_limited` with `Retry-After`, nginx's and
  the API's log lines without an address, migration 007 on PostgreSQL over reports of the
  old form.

## Deployment

- The operator: `[nogat.operator]` in `~/.config/nogat/nogat.toml`, and in production's
  `.env` `NOGAT_CONFIG=/home/claude-agent/.config/nogat/nogat.toml`.
- As root on the host: `install -m 644 docker/journald.conf
  /etc/systemd/journald.conf.d/hydrograf.conf && systemctl restart systemd-journald`
  (before `terms_effective`, or the journal keeps the logs longer than the regulamin says).
- Production (`~/workspace/Hydrograf`): after the merge and the checkout,
  `docker compose up -d --no-deps api nginx`. Both containers are recreated: new mounts,
  environment and log driver; migration 007 runs when the API starts; `nginx.conf` is a
  single-file mount, so a reload would not see the new file.
- Cloudflare Access on `/admin`, `/admin.html` and `/api/admin/*`.
- Hydroni (`docker-compose.prod.yml`, the code in the image `hydroni-api`): a build of the
  image, the API with one process (it loses its second worker); NOGAT_CONFIG and the
  `hydrograf` entry of HYDROGRAF_GUI are its own decision.
- The 30 reports of production's old form (ids 11–40) keep their old columns until the
  operator decides; a later migration drops the columns.
