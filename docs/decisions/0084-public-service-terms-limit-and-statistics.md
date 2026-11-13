# ADR-084: Hydrograf as a public service: the regulamin, the request limit in the app, logs without addresses, daily totals and a form without contact

**Date:** 2026-11-13
**Status:** accepted

## Context

The author ordered on 2026-11-13 one regulamin for every public GUI of the ecosystem and
the rules that make its text true. Nogat set them in DEV-15.7 to DEV-15.12 and the table
`operator` of DEV-18.1 (ECO-061 to ECO-063, kit 0.4.0 with regulamin 1.0, Nogat `develop`
`2b513d0`, its plan `docs/plans/2026-11-13-gui-terms.md`, step 3 for Hydrograf):

- DEV-15.7: the kit's `nogat-terms.html`, filled from `[nogat.operator]`, at
  `regulamin.html`; a link „Regulamin” in every view and in the app menu (`terms`);
- DEV-15.8: the statement of the service beside it;
- DEV-15.9: 300 requests in 60 s per client address by default, static files not
  counted, 429 with `Retry-After`, a Polish page or the problem `rate_limited`, the
  address in memory for the window only;
- DEV-15.10: no client address in any log, access, error or application; logs deleted
  after 14 days;
- DEV-15.11: daily totals only, a visitor being an HMAC of the address and the User-Agent
  under a salt drawn daily and kept in memory;
- DEV-15.12: „Zgłoś uwagę” with the text and the view's context, no contact field.

Hydrograf before this decision: nginx (`docker/nginx.conf`) limited `/api/` to 10 r/s
with a burst of 20, tiles to 30 r/s, the admin API to 5 r/s and the form to 1 r/min, keyed
by `$binary_remote_addr`; behind the Cloudflare Tunnel that is the tunnel connector's
address on the Docker network (172.18.0.1 on production), so every client shared one
bucket, and the 429 was nginx's HTML page (the AGI-6.3 deviation of `CLAUDE.md`). The
access log wrote `$remote_addr`, `$remote_user` and the referrer, the error log the
`error` level with `client:`, uvicorn its own access log, and json-file kept up to
500 MiB per container, months of lines. The form (ADR-053) sent an optional contact, the
page's URL and, opted in, diagnostics with the User-Agent, the URL and the last 50 events;
the server stored the User-Agent of every report. nginx served the HTML pages, which the
API never saw. Production's API runs one process (the development override, `--reload`),
the prod overlay two workers.

## Options

Limit:

- A. nginx `limit_req` keyed by the client's address (`real_ip_header CF-Connecting-IP`),
  the error log at `crit`: a leaky bucket, not „300 in 60 s”; `Retry-After` and the
  Polish text only as fixed strings; the daily totals still need the app.
- B. The app: one fixed window per address in the process's memory for pages and routes;
  the address from `CF-Connecting-IP`, believed only through the private hops of the
  tunnel and nginx; nginx never learns the client's address.

Pages:

- C. nginx serves the HTML and counts nothing: no page views, no limit on pages.
- D. nginx asks the API first (`auth_request`): a 429 page made by nginx.
- E. nginx passes each page to the API, which counts and limits it and answers
  `X-Accel-Redirect` to the file; nginx sends the file.

Logs kept 14 days:

- F. json-file or local: rotation by size only, the active file of nginx holds months.
- G. The journald driver and the host's journal with a time limit.
- H. Daily files and a pruning job of our own.

Reports of the old form (30 on production, 3 with a contact):

- I. Drop `contact` and `user_agent` and turn `page_url` and `diagnostics` into `context`:
  deletes what those reports hold before the operator has handled them.
- J. A column `context` for new reports; the old columns stay with the old reports until
  the operator has handled them, and a later migration drops them.

## Decision

B, E, G and J.

- The regulamin (`core/terms.py`): the kit's template (kit 0.4.0 copied into
  `frontend/nogat/`, mounted into the API at `/frontend/nogat`) filled once per process
  from `[nogat.operator]` of the `nogat.toml` in NOGAT_CONFIG (Docker mounts the host's
  file at `/config/nogat.toml`, `/dev/null` without it) and the entry `hydrograf` of the
  table `gui`; the blocks `pmaxtp` (with `imgw-terms`), `gugik`, `copernicus`, `isric`,
  `wody-polskie`, `osm` and `esri`; served at `/regulamin.html`. `GET /api/terms` gives
  the front end its address and the operator's e-mail, both null without an operator: no
  footer, no menu entry, no e-mail under the form. The table `gui` now comes from
  HYDROGRAF_GUI and, when that is empty, from the same file (DEV-18.1's order), which
  amends ADR-082.
- The footer of the map (`#site-footer`, `js/terms.js`) and of the guide: the statement
  and „Regulamin”; the app menu gets `terms`.
- The limit and the totals (`api/traffic.py`, `core/request_limit.py`, `core/usage.py`):
  a middleware inside the request ID's; pages and routes 300 in 60 s per address
  (HYDROGRAF_REQUEST_LIMIT, HYDROGRAF_REQUEST_WINDOW), map tiles ten times that in the
  same window instead, the form besides at most 5 reports in 5 minutes, `/health` not
  counted. Over a limit: `Retry-After` with the seconds to the end of the address's
  window, the Polish page for a page, the problem `rate_limited` for a route (documented
  as 429 of every `/api/` operation), which amends ADR-059. Ended windows are forgotten
  within 5 s. Visitors, page views (GET of a page served), analyses (successful
  delineations of a watershed or a network, hydrographs, terrain profiles) and downloads
  (`POST /api/downloads`, which the front end sends for each file it saves; it builds
  them in the browser) are stored as one line per UTC day of
  `<data_dir>/hydrograf/stats.jsonl` (HYDROGRAF_DATA_DIR, `/data` in Docker) every
  10 minutes, at 00:00 UTC and at shutdown; a restart adds to the day's line.
  `stations_opened` is 0: Hydrograf has no stations.
- One process: the prod overlay runs uvicorn without `--workers`, so the limit and the
  distinct visitors are those of the one process.
- nginx: no `limit_req`; the access log `$time_iso8601 "$request_method $request_uri"
  $status $body_bytes_sent request_time upstream_time request_id "$http_user_agent"`; the
  error log at `crit`; `X-Real-IP` is nginx's peer, `X-Forwarded-For` goes. Pages pass to
  the API (`\.html$`, `/admin` rewritten to `/admin.html`) and come back as
  `X-Accel-Redirect` to the internal `/_site/`; with the API down or starting nginx sends
  the file itself. uvicorn runs with `--no-access-log`; `api.main` logs each request
  with its method, path, status, duration and ID, never its client.
- The containers of nginx and the API log to journald (`tag` the container's name);
  `docker/journald.conf` gives the host's journal `MaxRetentionSec=12day` with daily
  files, at most 14 days. PostgreSQL keeps json-file: its log has no client of the
  service.
- „Zgłoś uwagę”: `{message, context: {view, station, parameters}}`, any other member
  refused with 400; the server adds `context.app_version` and stores no User-Agent.
  Migration 007 adds `context` and comments the old columns; the admin list gives each
  report `context` and `legacy` (the old fields, null for new reports). The form shows
  the DEV-15.12 line with the operator's e-mail; `js/diagnostics.js` with its event log
  and its wrapper of `fetch` is gone, which supersedes ADR-053.
- Admin: `/admin`, `/admin.html` and `/api/admin/*` stay, with `X-Admin-Key`; Cloudflare
  Access protects them in front of the tunnel.

## Consequences

- The address of a client exists only in the API's memory: in the window of its limit
  and, through the day, as a salted hash. nginx never knows it behind the tunnel; neither
  log of a request names it.
- Every page load costs one more request to the API, and pages count against the limit;
  a page still loads while the API restarts.
- The deployment sets NOGAT_CONFIG and installs `docker/journald.conf` before the date
  `terms_effective`; without the first there is no regulamin, without the second the
  journal keeps the logs longer than the regulamin says.
- Hydroni (prod overlay) loses its second worker: two heavy requests share one process's
  CPU, threads running the I/O and the GIL-free parts in parallel.
- The 30 reports of production's form before this decision keep their contact (3), page
  URL, User-Agent and diagnostics until the operator deletes them; the migration that
  drops those columns follows.
- `X-Request-ID` no longer reaches the operator through the form; a person who wants an
  answer writes an e-mail.
