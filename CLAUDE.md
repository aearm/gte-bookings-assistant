# Bookings Assistant

A web app (FastAPI in `server/`, React in `web/`) that answers questions about the company's bookings data from
Analysis Services cubes and keeps dashboards of charts. `README.md` explains everything for its users.

## Working with the data or the dashboards

Use the **bookings-assistant** connector (tools `get_knowledge`, `run_query`, `add_chart`...) and the
**bookings-dashboards** skill (`skills/bookings-dashboards/SKILL.md`): call `get_knowledge` first, check every
query with `run_query`, and change dashboards only through the connector's tools - never by editing
`dashboards.json` by hand. If the connector isn't connected: `.venv\Scripts\python.exe install\connect_claude.py`,
then start a new conversation.

## Working on the code

- Python 3.13 in `.venv`; Node for `web/` (`npm run build` into `web/dist`, which the server shows).
- Tests: `.venv\Scripts\python.exe -m pytest -q` (local mode, no cube and no Claude needed); in `web/`:
  `npx vitest run`, `npx playwright test`.
- `semantic/`, `skills/` and all code are public: no customer, hotel, supplier, agency or person names, and no
  customer codes. Company data (`.env`, `dashboards.json`, `data/`, `models/`) never goes into git.
- Releases: raise `VERSION` and add its `CHANGELOG.md` section; pushing that to `main` publishes the release.
