# API contract (v1)

The React app (`web/`) talks only to these endpoints; FastAPI (`server/`, started with `python start_api.py`)
implements them on top of the existing modules. JSON everywhere (dates `YYYY-MM-DD`, `end` exclusive = the
day after the last day), except the streams (`text/event-stream`, Server-Sent Events) and the CSV download.
All paths start with `/api`. The shapes are the models in `server/schemas.py` (mirrored by
`web/src/api/types.ts`); while the server runs, FastAPI lists the same endpoints at `/docs`.

Conventions
- **Errors**: `{"detail": "plain-English message", "details": "technical text (optional)"}` with 4xx/5xx.
  An unknown id gives 404 (`"This dashboard wasn't found. It may have been deleted, or the server restarted."`),
  a body or query that isn't valid 422 (`details` names the fields), anything unexpected 500, and an
  unknown `/api/...` path 404.
- **Admin**: endpoints marked 🔒 need the admin session cookie (`ba_session`, httpOnly, SameSite=Strict,
  Secure over https; a token signed with the admin password's hash, so changing the password signs every
  browser out); otherwise 401 `{"detail": "Sign in as admin to do this."}`.
- **Writes** (POST/PUT/PATCH/DELETE under `/api/`) must send the header `X-Requested-With: bookings-assistant`
  (CSRF guard); otherwise 403 `{"detail": "This request was refused: it didn't come from the app."}`.
- **Compression**: replies over 1 KB are gzipped when the browser accepts it (not the SSE streams).
- **Streams**: each message is `event: <name>\ndata: <json>\n\n`; a job stream that has been quiet for
  15 s sends a `: keep-alive` comment line.
- **Table** (results): `{"columns": [{"name": str, "type": "number"|"text"|"date", "format": {...}|null}], "rows": [[...]], "row_count": int, "truncated": bool}`
  (dates as ISO strings; numbers as JSON numbers; nulls as null; at most 5,000 rows, `row_count` is the
  full count; `format` = how the chart writes that number column, see `chart_options.py`).
- **Chart**: `{"kind": "<chart type or 'table' or 'kpi'>", "option": <ECharts option from chart_options.build_option, or null for a table or kpi>, "title": str, "summary": str, "note": str}`.
  Number formats inside options follow the declarative convention documented in `chart_options.py`. The
  option carries its own rows (its `dataset`).
- **Period**: `{"start": date, "end": date, "label": "This year · 1 Jan – 16 Oct 2026 · W1–42", "preset": str}`.
- **Comparison**: a Period (`label` = its dates, `preset` "") plus `"mode": "previous"|"last_year"|"custom"`
  and `"name"` (for "+12% vs <name>": "the 7 days before", "last year").
- **PeriodPick**: optional fields of the bodies that add or change dashboard charts, the dashboard's period
  at the time: `{"start"?, "end"?, "preset"?, "compare"?, "cstart"?, "cend"?}`, read as the query of
  `/results` (the default period when left out). Used to try a new query out, and to keep a chat answer's
  numbers as a chart's first ones for that period and comparison.
- **Picking a period** (`start,end,preset` everywhere): a known `preset` ("Last 7 days", as of today) wins,
  else `start` and `end`, else the default (`/info` `defaults`). `compare` is `none|previous|last_year|custom`
  (default `previous`); `custom` uses `cstart,cend`, or the previous period without them.

## Session
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /session | – | `{"admin": bool, "has_admin_password": bool}` |
| POST | /session | `{"password": str, "keep": bool = false}` | `{"admin": true, "has_admin_password": true}` + cookie (keep → 30 days, else a browser-session cookie whose token lasts a day); 401 wrong password (after a 1 s delay); 409 no admin password has been created yet |
| DELETE | /session | – | `{"admin": false, "has_admin_password": bool}`, cookie cleared |
| POST | /session/first-password | `{"password": str}` (8 characters or more, else 400) | only while no admin password exists (else 409): creates it and signs in (kept 30 days); `{"admin": true, "has_admin_password": true}` |

## App
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /info | query `scope` (optional: a cube's example questions instead of all the data's) | `{"version", "data_source": "ssas"\|"local", "ready": bool, "why": str, "scopes": [{"value": "", "label": "All data"}, {"value": cube, "label": ...}], "example_questions": [str] (up to 6), "defaults": {"preset": "Last 7 days", "compare": "previous"}, "chart_types": [{"value", "label"}], "width_choices": ["half", "full"]}` |
| GET | /health | – | `{"ok": true, "version", "data_source", "up_seconds", "workers": {"warm": bool, "mode": "processes"\|"in-process", "count": int, "pids": [int]}, "last_prerun": str}` |

`ready` is false (with `why`) until a cube is connected, the data layer is built (for All data) or the
scope's cube has been read, a Claude API key is set and, in live mode, a server is set. The "All data"
scope is listed only once the data layer is built. `defaults` come from `periods.py`
(`DEFAULT_PRESET`, `DEFAULT_COMPARE`). `chart_types` are the chart type pickers' choices (`auto`, `kpi`,
the chart types, `custom`).

`workers.warm`: the cube worker processes (`API_WORKERS`, live mode only; `"in-process"` with `count` 0
otherwise) are connected and the start-up warm-up (data layer, meaning layer, value indexes) is done.
`last_prerun`: when the dashboard charts were last run by the server itself (ISO time, "" before the first;
see Dashboards).

## Chat
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /conversations | `{"scope": ""}` ("" = All data, or a connected cube; else 400) | `{"id"}` |
| GET | /conversations/{id} | – | `{"id", "scope", "turns": [Turn]}` |
| POST | /conversations/{id}/ask | `{"question": str, "clarification": {"question"?, "answer"}?}` | **SSE stream** (below) |
| POST | /conversations/{id}/turns/{turn_id}/chart | `{"request": "as a pie"}` | `{"chart": Chart}` (redraw: one Claude call, no new query); 400 no numbers to draw; 502 Claude failed |
| GET | /conversations/{id}/turns/{turn_id}/csv | – | CSV download (`text/csv`, every row, named after the chart's title) |
| POST | /answers/{answer_id}/verify 🔒 | `{"verified": bool = true}` | `{"ok": true}` |
| GET | /history | – | `[{"time", "question", "rows", "title"}]` |

Conversations live in the server's memory: the least recently used beyond 200 are forgotten, and a restart
forgets them all (404).

Turn: `{"id", "question", "understanding", "query" (plan text), "cubes": [str], "explanation", "notes": [str], "periods": [{"phrase","start","end"}], "table": Table|null, "chart": Chart|null, "clarify": {"question","options","answered": bool}|null, "error": str|null, "details": str|null, "answer_id": int|null, "language": "DAX"|"SQL"|"", "verified": bool, "asked": str (when its numbers were read), "dashboard_modes": [ModeChoice]}`

ModeChoice: `{"mode": "own"|"fixed"|"dashboard", "label": "Own period: yesterday vs the day before (14–15 Oct)", "instant": bool}`,
the ways the answer can go on a dashboard, the suggested one first (`[]` for an answer without a chart).
`instant`: made in code at once (no Claude call, no query); otherwise Claude writes a new plan for it.

With `clarification`, the question asked is the open clarifying question's original one (`question` may be
empty). SSE events of `/ask`:
`step {"text"}` (progress lines) → `data {"table": Table}` → `chart {"chart": Chart}` → `done {"turn": Turn}`,
or `step` → `clarify {"question","options"}` → `done {"turn": Turn}`; on failure `error {"message","details","turn"}`
(no `done`; the failed turn stays in the conversation). If the browser goes away, the question still
finishes and its answer stays in the conversation.

## Dashboards
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /dashboards | – | `[{"id","name","charts": int}]` |
| POST | /dashboards 🔒 | `{"name"}` | Dashboard |
| PATCH | /dashboards/{id} 🔒 | `{"name"}` | Dashboard |
| DELETE | /dashboards/{id} 🔒 | – | `{"ok": true}` |
| GET | /dashboards/{id} | – | Dashboard |
| GET | /dashboards/{id}/results | query `start,end,preset,compare,cstart,cend,force(bool)`, and `f_<key>=<value>` for each of the dashboard's filters | `{"period": Period, "compare": Comparison\|null, "data_as_of": {"text": "Data updated 13 Oct, 18:24", "per_cube": {cube label: "13 Oct 2026, 18:24"}}, "charts": {chart_id: ChartResult}, "updating": bool, "filters": {key: value used}}` |
| GET | /dashboards/{id}/filters | – | `[{"key", "label", "options": [{"value", "label"}], "default", "error"}]`: the values each filter of the dashboard can take (e.g. the clients with sales in the last year, biggest first; kept for hours) and its default (the first). `[]` for a dashboard without filters |
| POST | /dashboards/{id}/charts 🔒 | `{"question", "title"?, "chart_type": "auto", "width": "half", "cube": "" (= All data), "date_column"?, "period_mode": "dashboard", "chart_request"? (for `custom`)}` + PeriodPick | ChartMeta (Claude writes and tests its query; slow path) |
| POST | /dashboards/{id}/charts/from-answer 🔒 | `{"conversation_id", "turn_id", "period_mode"?: "own"\|"dashboard"\|"fixed", "title"?, "width"?, "chart_type"?}` + PeriodPick | ChartMeta (instant when that way is `instant`) |
| POST | /dashboards/from-conversation 🔒 | `{"conversation_id", "name", "turn_ids"?: [str]}` + PeriodPick | Dashboard (with `failed`) |
| POST | /dashboards/{id}/starter 🔒 | `{"cube"}` + PeriodPick | `{"job": id}` (suggested charts for an empty dashboard, built by Claude from a set-up cube) |
| PATCH | /dashboards/{id}/charts/{cid} 🔒 | any of `{"title","chart_type","width","date_column","period_mode","compare": bool,"question","chart_request","query"}` + `start,end,preset` | ChartMeta |
| GET | /dashboards/{id}/charts/{cid}/modes | query `start,end,preset` | `{"current": mode, "choices": {mode: label}}` |
| POST | /dashboards/{id}/charts/{cid}/restyle 🔒 | `{"request"}` + PeriodPick | ChartMeta (one Claude call; 400 for a headline number) |
| POST | /dashboards/{id}/charts/{cid}/send 🔒 | `{"to": dashboard_id\|"new", "move": bool, "name"?: str}` | `{"ok": true, "to": dashboard_id}` |
| POST | /dashboards/{id}/charts/{cid}/move 🔒 | `{"step": -1\|1}` | Dashboard |
| DELETE | /dashboards/{id}/charts/{cid} 🔒 | – | `{"ok": true}` |
| GET | /date-columns | query `cube` ("" = All data) | `{"options": [{"value","label"}], "default": str}` |
| GET | /periods | query `start,end,preset,compare,cstart,cend` | `{"presets": [{"name","start","end","label"}], "compare_modes": [{"mode","label","dates"}], "period": Period, "compare": Comparison\|null, "defaults": {"preset","compare"}}` |

Dashboard: `{"id","name","charts": [ChartMeta],"filters": [{"key","label"}],"failed": [{"turn_id","title","error"}]}`
(`failed` only from `/dashboards/from-conversation`: the answers that couldn't be prepared; the others were
added). `filters`: the dashboard's own filters above its charts (e.g. `client`, `market` on the built-in Client
and Market views); the page keeps the value picked in its address as `f_<key>` and sends it to `/results`.
ChartMeta (`lower_is_better`: a headline number whose fall is good news, e.g. look-to-book): `{"id","title","question","chart_type","width": "half"|"full","cubes": [str],"date_column","period": {"mode": "dashboard"|"own"|"fixed","label": "Own period: yesterday vs the day before (14–15 Oct)"},"compares": bool,"lower_is_better": bool,"caption","date_label","sources": [cube label],"compare_on": bool,"chart_request","query","query_editable": bool}`
(`period.label` is "" for a chart that follows the dashboard; `compare_on` = the admin's switch for the
comparison, `compares` = whether the chart shows it (only charts that follow the dashboard, and only
headline numbers, tables, and columns, bars or lines of one measure); `query_editable` = a one-step plan,
editable by hand).
ChartResult: `{"chart": Chart|null, "table": Table|null, "prev_table": Table|null, "kpi": {"value","text","change","change_text": "+12.3% vs the 7 days before" (a percentage measure, e.g. a margin, changes in points: "+3.2 pts vs ...", and "change" is then that difference),"prev_text","prev_label"}|null, "error": str|null, "details": str|null, "period_label": str}`
- When `chart.option` is set, `table` and `prev_table` are null: the chart carries its rows in its dataset.
  They are sent for a chart shown as a table (`option` null; with a change column per measure when
  compared), for a headline number (`kind` "kpi", with `kpi`), and for a period with no data.
- `period_label`: the chart's own period, or the dashboard's dates. `error` "No numbers yet for this chart."
  when it has none.

`/results` gives the saved numbers at once and runs the missing ones now. `updating: true` → poll `/results`
again every 3 s until false (charts whose cube has new data are refreshed in the background). The cubes'
update times are asked at most every 5 minutes, and a page waits at most 2 s for them (the last ones
otherwise); `force=true` asks again and runs every chart now. The server runs the charts itself at start-up
and every day at 00:05 (charts with periods of their own for the new day, and every chart for the default
period and comparison), so the first visit of the day opens with saved numbers.

Chart periods (`period_mode`): `dashboard` follows the dashboard's period; `own` keeps the question's own
rolling dates ("yesterday vs the day before", worked out again every day); `fixed` keeps the exact dates.
- **from-answer**: `period_mode` defaults to the turn's first `dashboard_modes`; a mode not in that list is
  a 400. An `instant` way is made in code: the answer's plan with its dates as placeholders, its chart as
  drawn in Chat, and the chat's numbers kept as its first ones (when they are what it shows for the
  PeriodPick). Otherwise Claude writes a plan for the dashboard's period.
- **from-conversation**: every answer with a chart (or only `turn_ids`) goes its suggested way, in the
  conversation's order: instant ones at once, the others prepared by Claude at the same time; 400 when
  none could be prepared (no dashboard is made).
- **PATCH**: a new `question`, another `date_column` or switching to or from `kpi` has Claude write a new
  query; a new `chart_request` for a `custom` chart has Claude redraw it; `query` edits a one-step query by
  hand; everything else is done in code. Switching `period_mode` is done in code when the query allows it,
  else (to follow the dashboard) Claude writes a new query. Here `compare` is the chart's switch for the
  dashboard's comparison (`false` = off), not a comparison mode; only `start,end,preset` of PeriodPick apply.
- **/modes**: the ways the chart can switch to in Edit, for the dashboard's current period ("Follow the
  dashboard's period" is always offered, with "(Claude writes a new query for it)" when it can't be done in code).
- `chart_type`: a key of `/info` `chart_types` ("pie" is taken as "donut"; `auto` not on PATCH; `custom`
  needs `chart_request`). `date_column`: null or left out → the cube's main date; "" → always all dates;
  `"auto"` → each cube's main date (All data). `/date-columns` lists them, the last option being
  `{"value": "", "label": "Nothing (always show all dates)"}`.
- **send**: copies the chart to another dashboard, or moves it (`move: true`); `to: "new"` makes a new
  dashboard named `name` ("New dashboard" without one). 400 when `to` is the same dashboard.
- `/periods` `compare_modes[].dates`: that comparison's dates for this period, or "Show this period only".

## Meaning layer & glossary
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /glossary/{cube} | – | `{"cube","label","summary","rows": [{"Term","Meaning","Measure","Date to use","Status": "Draft"\|"Agreed","Agreed by"}],"updated","drafts": int,"columns": [str],"statuses": [str]}`; 404 for a cube that isn't connected |
| PUT | /glossary/{cube} 🔒 | `{"rows": [...]}` | same (Claude uses it from the next question) |
| GET | /decisions | query `cube` (optional) | `{"open": int (across all cubes), "items": [{"id","cube","question","why","options","proposed","answer","status": "proposed"\|"agreed"}]}` |
| POST | /decisions/{id} 🔒 | `{"answer"}` | item |

## Cubes & data layer 🔒 (every endpoint here, and /jobs)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /cubes | query `fresh` (bool) | `{"server_cubes": [str], "server_cubes_detail": [{"name","label","updated"}], "server_error": str, "local": bool, "server": str, "enabled": [str], "cubes": [{"name","label","ready","setup": str,"usable": bool,"coverage": str,"in_layer": bool}], "layer": {"built","model","cubes","missing","changed","entities","ready"}, "drift": [str], "meaning": {"decisions","agreed"}, "layer_model": str}` |
| PUT | /cubes/enabled | `{"names": [str]}` | as GET (the existing order kept, new ones at the end); 400 in local mode or for a cube not on the server |
| POST | /layer/build | `{"cubes": [str]\|null, "only_changed": bool}` | `{"job": id}` (one build at a time: a running one's id) |
| GET | /cubes/{cube}/setup | – | `{"cube","label","status","progress": {"structure","drafted","questions","proposals","ready"},"structure_read","summary","drafted","questions": [{"index","term","question","options"}],"proposals": [{"index","term","meaning","in_data"}]}` |
| POST | /cubes/{cube}/setup/read | – | `{"job": id}` (step 1: read the cube's structure and values again) |
| POST | /cubes/{cube}/setup/draft | – | `{"job": id}` (step 2: Claude drafts the map; 400 before the structure is read) |
| POST | /cubes/{cube}/setup/answer | `{"index","option"?,"custom"?}` | setup state |
| POST | /cubes/{cube}/setup/skip | `{"index"}` | setup state |
| POST | /cubes/{cube}/setup/confirm | `{"indexes","rejected"}` | setup state |
| GET | /jobs/{id} | – | `{"id","kind","status": "running"\|"done"\|"failed","lines": [str],"started","finished","error"?,"details"?}` |
| GET | /jobs/{id}/events | – | SSE `line {"text"}` (earlier lines first) … `done {"status","error"?,"details"?}` |

`/cubes`: the server's list of cubes is asked at most every 10 minutes (`fresh=true` asks now), and a page
waits at most 5 s for it. A busy server (e.g. while it refreshes a cube) gives the last list, or, before
the first one, an empty list and a `server_error` saying so. `PUT /cubes/enabled` waits up to 30 s. In
local mode the server's list is empty. Jobs are kept in the server's memory (the last 100).

## Settings (🔒 except GET /settings, which shows whether things are set, never values)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /settings | – | `{"api_key": "set"\|"missing", "api_key_where": "saved"\|"env"\|"missing", "server": {"address","database","login_saved": bool,"windows_login": bool,"username" (admins only)}, "admin_password_set": bool, "data_source", "models": {"questions","fast","layer"}}` |
| PUT | /settings/api-key 🔒 | `{"key"}` (starts with `sk-ant-`, else 400) | status |
| POST | /settings/api-key/test 🔒 | – | `{"ok": bool, "model", "detail"?, "details"?}` (asks the API about the model; uses no tokens) |
| PUT | /settings/server 🔒 | `{"server","database"?,"username"?,"password"?}` (a new username needs its password) | status |
| POST | /settings/server/test 🔒 | – | `{"ok": true, "cubes": int}` (the cubes this login can open); 400 with the reason when it can't connect, or in local mode |
| PUT | /settings/admin-password 🔒 | `{"current","new"}` (8 characters or more) | `{"ok": true}` + a new cookie (every other browser is signed out); 400 wrong current password (after a 1 s delay) |
| GET | /updates 🔒 | query `fresh` (bool) | `{"current","latest","published","notes","page","developer_copy": bool,"last": {...}\|null,"error","status": "updating"\|"up_to_date"\|"available"\|"no_release"\|"check_failed"}` |
| POST | /updates/apply 🔒 | – | `{"started": true, "version"}`; 409 an update is running; 400 a developer copy (git) or no newer version |

`/updates` asks GitHub at most every 5 minutes (`fresh=true` asks now); `last` = how the last update went,
`error` = a download that failed after `/updates/apply`.

## Usage 🔒
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /usage | query `days=30` (1–366) | `{"report": {...usage.cost_report()}, "recent": [entry] (the latest 300 questions, newest first), "summary": {"questions_7d","median_seconds","average_cost","cost_7d","from_memory_7d"}}` |

## The React app (paths outside /api)
- `GET /assets/...`: the built JavaScript, CSS and fonts in `web/dist/assets` (their names change with
  every build, so browsers keep them).
- Any other `GET`: that file of `web/dist` if it exists, else `index.html` (`Cache-Control: no-cache`, so a
  new version shows on the next reload), so the app's own routes work on reload; 503
  `{"detail": "The React app isn't built yet: cd web && npm run build"}` when there is no build.
