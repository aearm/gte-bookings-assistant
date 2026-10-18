# Refactor plan: React + FastAPI, faster and more performant

Goal: replace the Streamlit front end with a React app and serve it from a FastAPI back end, so that
pages open instantly, interactions don't re-run the whole page, several people can use the app at
once without slowing each other, and charts render fast at any size. Accuracy must stay where the
test set has it (92% of 180 trials, `v3-k3`).

## 1. Targets (measured today → target)

| What | Today (Streamlit 1.1.2) | Target |
|---|---|---|
| Open a dashboard (warm server) | 2.2 s | **< 0.8 s** (saved results), < 0.3 s on repeat visits (browser cache) |
| First page after a server restart | 18–21 s | **< 2 s** (workers warm at start-up, not on the first page) |
| Change period / compare (data cached) | 1–3 s (whole page re-runs) | **< 300 ms**; < 50 ms with DuckDB-WASM filters |
| Chat: first visible progress | ~1 s | **< 300 ms**, then data → chart → streamed answer |
| Chat answer, median / slowest tenth | 16 s / 24 s | ≤ 12 s / ≤ 20 s (no UI overhead, parallel steps) |
| 10 people at once | each page slows the others (one Python process, shared lock) | **no visible slowdown** (load test) |
| Server CPU when idle | 1% (was 100% in the sign-in loop) | ~0% |
| Initial JavaScript download | — | < 350 KB gzipped (maps, DuckDB-WASM loaded only when used) |

## 2. Why the current app is slow (measured this week)

1. **Streamlit re-runs the whole page script on every click** (period change, menu, dialog) and
   re-sends every element; heavy pages pay their full cost on each interaction.
2. **One Python process serves everyone.** Threads take turns on Python's lock (GIL). Reading cube
   rows through the .NET connector makes one call per cell, and each call hands the lock back and
   forth: a background refresh slowed pages 6× (13 s), and pages starved the refresh (minutes).
3. **Big cube results are slow to transfer**: 67,500 rows took 26 s. Measured (16 Oct): ~23.5 s of it is the
   server streaming ~100 MB of XML at ~4.3 MB/s; reading row by row in Python added 1–2.5 s, but made
   every other thread crawl (a read under load did not finish in 4 minutes). Queries that reached their
   row limit also waited for every remaining row (23.9 s for 5,000 of 129,843 rows).
4. **Start-up work lands on the first visitor**: imports (.NET bridge, Plotly), value indexes, and a
   Streamlit check that resolved every module's path (minutes on a busy server).
5. **Browser-side state round-trips** (the "keep me signed in" component) can loop, re-running the page
   endlessly.

The rebuild removes 1, 4 and 5 by design, and 2–3 with process isolation and a bulk reader.

## 3. Target architecture

```
Browser (React SPA, served as static files)
  ├─ TanStack Query: cache, background refresh, retries          ─┐
  ├─ ECharts (canvas): every chart type, dataset/encode           │  HTTPS, same origin
  ├─ Arrow IPC results → DuckDB-WASM (phase 6, instant filters)   │  JSON + Arrow + SSE
  └─ SSE: chat progress, job progress, dashboard updates         ─┘
FastAPI (one API process, uvicorn, async)
  ├─ async endpoints; Claude calls with AsyncAnthropic (I/O, no lock contention)
  ├─ thread pool: light blocking I/O (files, SQLite)
  ├─ query worker processes (2–4, warm): ADOMD.NET + DuckDB; one per CPU-heavy job
  │     → a cube query never shares Python's lock with the API
  ├─ job manager: cube setup, data-layer builds, dashboard refreshes, test runs (progress via SSE)
  └─ existing domain modules, unchanged: answering, plans, rewrite, routing, semantic, llm,
     dashboards, data_layer, value_index, glossary, cube_setup, updates, usage, eval_set
Storage (local, unchanged locations): dashboards.json, data/*.db, models/, results as Parquet/Arrow
```

### Key choices (and why)

| Choice | Decision | Why |
|---|---|---|
| Server | **FastAPI + uvicorn**, async; **processes** for cube work, threads only for I/O | "Multi-threading" alone keeps the lock problem (§2.2). Async handles many users; separate processes make cube reads and DuckDB joins truly parallel. |
| Data | **DuckDB + Apache Arrow** (Polars not needed) | DuckDB already joins the cube steps and runs the SQL Claude writes; Arrow moves results without copies (worker → API → browser → DuckDB-WASM). Polars would add a second engine for the same job. |
| Charts | **ECharts** (uPlot only if we ever plot 100k+ point time series) | ECharts covers every chart the app draws: bars, lines, areas, stacked, donut, treemap, heatmap, scatter, world map, several y-axes, small multiples, data zoom, progressive rendering. uPlot is time-series only. |
| Chart spec | **Built on the server** (port of `charts.py` rules) as an ECharts option using `dataset` + `encode` | One place for the formatting rules (currency, %, panels, one chart with an axis per measure, comparison in grey, category axes, sorting), testable with pytest; the browser can swap the dataset (DuckDB-WASM filters) without rebuilding the option. |
| Described ("custom") charts | Claude writes an **ECharts option** with `{"col": ...}` references, checked on the server (no code executed) | Same safety as today's Plotly specs. Saved Plotly custom charts: converted once by a migration script; a lazily loaded Plotly renderer as fallback. |
| Front end | **React 19 + TypeScript + Vite**, React Router, **TanStack Query**, Zustand, Mantine (or shadcn/ui), echarts-for-react | Mature, fast builds, code splitting; Query gives stale-while-revalidate caching for free. |
| Streaming | **Server-Sent Events** | Chat steps, data, chart and answer text arrive as they are ready; job progress; "new numbers ready" on dashboards. Simpler than WebSockets, works through proxies. |
| Auth | Admin session in an **httpOnly cookie** (+ CSRF token), "keep me signed in" = longer cookie | No browser-side token round trip (the loop class disappears). |
| Faster cube reads | **Bulk reader** (done): a small .NET helper (built with Windows' csc.exe) returns a whole result in one call; **stop the server** at the row limit; next: **parallel date-range reads** for big results | The transfer from the server is the real cost (~4 MB/s per connection), so fewer rows (`@KEYS`, saved results) and parallel connections matter more than parsing. |
| Delivery | **Build the React app in GitHub Actions**, ship `web/dist` inside the release zip | Installations need no Node.js; the in-app updater keeps working. Node is only needed on a developer machine. |

## 4. What stays, what changes

| Area | Stays | Changes |
|---|---|---|
| Question answering | `answering`, `plans` (incl. `@KEYS`), `rewrite`, `routing`, `semantic`, `llm`, `value_check`, `data_tools`, `answer_memory` | Progress callbacks become SSE events; Claude calls via the async client |
| Cube access | `ssas.py` query building, `backends`, `value_index` | Runs inside worker processes; bulk reader replaces row-by-row fetch; results as Arrow |
| Joins | DuckDB `combine` | Arrow in / Arrow out; result cache as Parquet (not pickle) |
| Dashboards | `dashboards.py` (plans, saved results, background refresh, periods, compare) | Refresh jobs in worker processes; SSE "updated" event replaces the Streamlit fragment |
| Charts | Rules in `charts.py` (fit, formats, panels, one chart, comparison, codes as categories, long periods over time) | Output = ECharts option + dataset instead of a Plotly figure; `dynamic_chart.py` checks ECharts options |
| UI | — | `app.py`, `ui.py`, `dashboard_view.py`, `period_picker.py`, `admin.py`, `inline_component.py`, `views/*` → React (`web/`) |
| Admin, settings, updater | `secrets_store`, `updates.py` (release zip, backup, rollback) | Endpoints; the updater also installs `web/dist`; start script runs uvicorn |
| Tests | 133 pytest tests, `eval_set.py` (60 questions) | + API tests, + Playwright end-to-end, + load test |

## 4b. Chart periods (fixes "added to a dashboard it looks different" and the 40–60 s add)

Measured on 16 Oct: adding a chat answer to a dashboard took 39–60 s (Claude re-plans 7–14 s, the new
plan runs over the whole dashboard period 14–47 s) and the chart changed: the question's own dates
("yesterday vs the day before") were replaced by the dashboard's period (or by no dates at all), and
its chart settings (one chart, a shade per day) were formatted again from scratch.

1. **Every chart has a period mode**
   - *Follows the dashboard*: default for questions without dates ("sales by month").
   - *Own rolling period(s)*: kept in the period grammar of `rewrite.py` (unit + offset, e.g. day -1 and
     day -2), so "yesterday vs the day before" moves forward every day. Default when the question names
     its own periods.
   - *Fixed dates*: a snapshot that never moves.
   A label on each chart says which ("Own period: yesterday vs the day before"); Edit switches it.
2. **Adding from Chat is instant**: no Claude call, no query. Code replaces each period's first/last
   dates in the chat's plan with placeholders (`@P1_START`, `@P1_END`, `@P2_…`; `@START/@END` for
   charts that follow the dashboard), stores the period definitions, the chat's chart settings, and
   the chat's result as the chart's first saved numbers. Target < 1 s (from 40–60 s).
3. **What you saw is what you get**: chart type, colours, one chart / panels and formats are kept.
4. **Grain adapts** when a by-day chart follows a long dashboard period: ≤ 31 days by day, ≤ 6 months
   by week, longer by month (queries stay small, charts stay readable).
5. **Two kinds of comparison**: a chart's own periods (yesterday vs the day before) vs the dashboard's
   Compare (whole dashboard, for charts that follow it).

Implemented in the back end first (`dashboards.py`, `plans.py`), so the current app gets it now and the
React app reuses it.

## 5. API (first version)

| Area | Endpoints |
|---|---|
| Session | `POST /api/session` (sign in, keep me signed in), `DELETE /api/session`, `GET /api/session` |
| Chat | `POST /api/ask` → SSE: `step`, `clarify`, `data` (Arrow), `chart` (option), `answer` (text chunks), `done`; `POST /api/ask/{id}/chart` (change chart, no re-query); `GET /api/history` |
| Dashboards | `GET/POST/PATCH/DELETE /api/dashboards[/{id}]`; `POST /api/dashboards/{id}/charts` (from a question, a chat answer, or a whole conversation); `PATCH/DELETE …/charts/{cid}`; `POST …/charts/{cid}/restyle`; `POST …/charts/{cid}/send` (copy/move) |
| Dashboard data | `GET /api/dashboards/{id}/results?start&end&compare=` → saved results at once + list of charts updating; `GET /api/dashboards/{id}/events` (SSE "chart updated"); `POST …/refresh` |
| Meaning layer & glossary | `GET /api/glossary/{cube}`, `PUT /api/glossary/{cube}`, `GET /api/decisions`, `POST /api/decisions/{id}` |
| Cubes & data layer | `GET /api/cubes`, `POST /api/cubes/enable`, `POST /api/layer/build` (job), `GET /api/jobs/{id}/events` |
| Settings & updates | `GET/PUT /api/settings` (API key, password), `POST /api/settings/test-key`, `GET /api/updates`, `POST /api/updates/apply` |
| Usage | `GET /api/usage?from&to` |
| Health | `GET /api/health` (workers warm, cube server reachable) |

## 6. Phases

Estimates are focused working days; each phase ends with its checks passing and nothing removed from
the running app until phase 5.

| # | Phase | Deliverables | Exit check | Days |
|---|---|---|---|---|
| 0a | **Chart periods (now, in the current app)** | §4b: period modes, instant add from Chat, chart kept as seen, adaptive grain, chart-own comparisons | Add to dashboard < 1 s; the added chart matches Chat; pytest green | 3 |
| 0 | **Baseline & tooling** | Install Node.js LTS (dev only), FastAPI, pyarrow; Playwright; performance script recording the §1 numbers for the current app; API contract (OpenAPI) | Baseline numbers saved; empty React app served by FastAPI on port 8600 | 2 |
| 1 | **API on the existing modules** | Endpoints of §5; worker processes for cube work; SSE chat; cookie sessions; job manager | API tests green; the 10 queries of §7 answered through the API with the same numbers as `v3-k3` | 6–8 |
| 2 | **Fast data path** | ✅ Bulk .NET reader (one call per result; no lock contention) and stop-sending at the row limit (23.9 s → 2.3 s); next: split big reads into parallel date ranges (67,500 rows: 26 s → 7.2 s measured), Arrow end to end, Parquet result cache, warm workers | Big reads ≤ 8 s; pages unaffected by reads; first request after restart < 2 s | 3–5 |
| 3 | **React: dashboards + chat** | App shell & navigation; dashboards (period calendar with ISO weeks, compare, KPI cards, chart cards, add/edit/restyle/copy/move/delete, new/rename/delete dashboard, saved numbers + live update); chat (streaming, clarify, follow-ups, change chart, add to dashboard, dashboard from conversation, query viewer, download); ECharts renderer for every chart type | Playwright scenarios §7 pass on port 8600 | 12–15 |
| 4 | **React: admin pages** | Cubes (connect, build/update data layer with progress), Glossary (decisions, edit), Settings (key, password, updates), Usage | All admin scenarios pass | 5 |
| 5 | **Test, measure, switch over** | Full §7 suite + `eval_set` 60×3 + load test (10 users) + §1 budget; run both apps side by side for a week; switch the Windows task to the new server; release **2.0.0** (updater ships `web/dist`) | §1 targets met; accuracy ≥ `v3-k3`; rollback to 1.1.x tested | 5 |
| 6 | **DuckDB-WASM** | Results arrive as Arrow; the browser loads them into DuckDB-WASM (lazy, only on pages that need it) for instant filters, top-N switches, search and drill-down without a server round trip; size guard (only datasets up to a few hundred MB; above that, the server filters) | Filter changes < 50 ms on a 1M-row dataset; initial page unaffected (WASM loaded on first use) | 5 |

Total ≈ 38–45 working days. Phases 1–2 can overlap with 3; the current app keeps running until phase 5.

## 7. Test plan: 10 questions and the interactions around them

Run automatically with Playwright against the new app (and once against the old one for comparison).
Numbers are checked against the same reference queries `eval_set.py` uses (computed at run time).

**Claude cost rule:** the suite runs without the Claude API: each question's plan and chart are
recorded once and replayed (the cubes are still queried live, so numbers stay real). A live check
with the app's Claude key uses **at most 2 questions, and only after the owner has enabled the key
for it**. A full `eval_set` run (60 × 3, $7–20) happens only when the owner asks for one.

| # | Question / interaction | Checks |
|---|---|---|
| 1 | Sales and profit by month, Jan–Sep 2026, as a line chart | 2 lines, AED format, totals = reference |
| 2 | Bookings by destination country, Sep 2026, on a map | world map, every country, total = reference |
| 3 | Share of bookings by sale channel, Q3 2026, as a donut | donut, % labels, total = reference |
| 4 | Bookings by sale channel and month, Jul–Sep 2026, heatmap | heatmap, total = reference |
| 5 | Top 10 customers by sales Q3 2026 with bookings and payments, horizontal bars | 2 cubes, top 10 = reference, ranked |
| 6 | Top 10 customers by bookings yesterday vs the day before: requests, bookings, sales, one chart, 6 bars each | 2 cubes with `@KEYS`, one chart with 3 axes, 2 shades |
| 7 | Per sale channel Sep 2026: searches, web/XML requests, bookings, payments, locks, as a table | 5 cubes, every column = reference |
| 8 | Follow-up "and the same for August 2026?" after #3-like question | standalone question, Aug dates, total = reference |
| 9 | Follow-up "as a line chart" | redrawn without a new query (no plan call) |
| 10 | "Compare errors this week with last week" | asks back with options (no guessing) |
| A | Add #1 to a new dashboard; open it | chart shows the dashboard period; opens < 0.8 s |
| B | Change period (preset, days, ISO weeks 40–41), compare last year / previous / off | numbers follow; < 300 ms when cached |
| C | Edit chart (title, type, width), restyle in words, copy & move to another dashboard, delete | persists after reload |
| D | Make a dashboard from the conversation (#1–#6) | 6 charts, all render |
| E | Saved numbers + background refresh (cube updated) | old numbers at once, new ones appear by themselves, page stays responsive |
| F | Sign in / keep me signed in / sign out; admin pages locked when signed out | no loop; cookie expiry honoured |
| G | Glossary: agree to a decision; Cubes: update one cube's layer (job progress); Settings: test the API key; check for updates | job progress streams; settings saved |
| H | 10 simulated users opening dashboards and asking questions at once | no request slower than 2× its single-user time |

Plus: the existing pytest tests and API tests (no Claude calls). `eval_set` 60×3 only on the owner's request, to confirm accuracy has not dropped before the 2.0.0 release.

## 8. DuckDB-WASM (phase 6) – when and how

- **When**: a chart or table whose data is already in the browser and the user wants to slice it
  (pick customers, markets, a sub-period, top-N, search) – instant, no server call. Not for new
  questions (those need the cubes) and not above a few hundred MB per dataset (memory in the tab).
- **How**: results are sent as Arrow IPC (compact, typed); the browser registers them in DuckDB-WASM
  (loaded lazily, ~6–8 MB, cached by the browser); filters run SQL in a Web Worker; ECharts swaps
  its `dataset`. Dashboards can pre-load the period's data for their slicers.
- **Guard rails**: size check before loading; fall back to server-side filtering above the limit;
  data stays in the tab (cleared on sign-out); same access rules as the page that showed it.

## 9. Switch-over and release

1. New app runs beside the old one (old 8501, new 8600) on the same data files.
2. When §7 and §1 pass: the Windows task starts the new server on 8501; the old start script stays
   for one release as a fallback.
3. Release **2.0.0**: the release zip contains `web/dist`; the updater installs it, keeps all data,
   and can roll back to 1.1.x.
4. Dashboards, glossary, answer memory, usage and history carry over unchanged; saved Plotly custom
   charts are converted once (fallback renderer otherwise).

## 10. Risks

| Risk | Mitigation |
|---|---|
| Missing a feature in the rebuild | Feature checklist from the current UI (8 dashboard dialogs, chat actions, 5 pages); Playwright suite; side-by-side week |
| .NET connector in worker processes (Windows sign-in, start-up time) | Spike in phase 1; workers stay warm; fall back to one worker per cube server |
| Bulk reader doesn't speed things up enough | Keep row reader in workers (still no lock contention for pages); `@KEYS` already shrinks big results |
| Chart parity (Plotly → ECharts) | Port rules with the existing chart tests; visual snapshots of each chart type |
| Node.js toolchain | Only on the developer machine; builds in GitHub Actions |
| Scope creep | DuckDB-WASM only after parity (phase 6) |

## 11. Decisions needed

1. **ECharts** as the chart library (uPlot only for very large time series later) – recommended.
2. **DuckDB + Arrow** (no Polars) – recommended.
3. **Side-by-side, switch at parity** (not a big-bang) – recommended.
4. **Install Node.js LTS** on this server for development (download from nodejs.org).
5. **Dashboard defaults** (asked earlier): period = last 7 days, and comparison = "yesterday vs the day
   before" – does that mean (a) the period is one week and the comparison is the previous week, (b) the
   default period is yesterday compared with the day before, or (c) the period is one week and each
   day is compared with the day before it?
