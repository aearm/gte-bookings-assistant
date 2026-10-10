# Bookings Assistant

Ask questions about your Analysis Services cubes in plain English and get the best-fitting chart
(world map, trend, donut, treemap, heatmap...), a short written answer, and the data. Keep useful
answers on named dashboards. Admins connect the cubes and set each one up once, answering a few
plain-language questions so Claude understands your business words.

The app has two modes and picks one automatically:

| | **Live mode** (Windows) | **Local mode** (Mac, or any computer) |
|---|---|---|
| Data | The cubes on your Analysis Services server (chosen on the **Cubes** page) | CSV / Excel files in `data/local` (sample data included) |
| Claude writes | DAX | SQL |
| Needs | ADOMD.NET + server login | Nothing extra |

```
Your question  ->  Claude writes a query  ->  runs against the live model or local files
               ->  results saved as CSV   ->  Claude picks a chart + writes the answer
```

Queries are read-only: nothing is ever changed in the model or the files.
To force a mode, set `DATA_SOURCE=ssas` or `DATA_SOURCE=local` in `.env`.

**Before you start:** check with IT that it's OK to send booking query results to the
Claude API. Table/column names and query results are sent to Claude.

---

## Mac setup (local mode, about 5 minutes)

1. **Install Python** from https://www.python.org/downloads/macos/ (any 3.12 or 3.13
   "macOS 64-bit universal2 installer"). Open the .pkg and click through.
2. **Get a Claude API key** at https://platform.claude.com/settings/keys.
3. **Unzip this folder**, e.g. into Documents.
4. Open **Terminal** (Cmd+Space, type Terminal), type `cd ` (with a space), drag the
   `bookings-assistant` folder into the Terminal window, and press Enter. Then run:
   ```
   bash setup.sh
   ```
5. **Add your API key:** run `open -e .env`, paste the key after `ANTHROPIC_API_KEY=`, save.
6. **Start the app:**
   ```
   bash run_app.sh
   ```
   Your browser opens at http://localhost:8501. Press Ctrl+C in Terminal to stop it.

It starts with made-up sample data (`data/local/sample_bookings.csv`), so you can try
questions straight away. To use real data, export a table from Excel as CSV into
`data/local` (see `data/local/README.txt`).

---

## Windows setup (one click, about 5 minutes)

**Before you start:** check with IT that it's OK to send booking query results to the
Claude API. The model's table/measure names and the query results are sent to Claude.
You need a Claude API key from https://platform.claude.com/settings/keys (add billing, then
create a key) and the server details you use in Power BI or Excel.

1. **Download and unzip** the app somewhere simple, e.g. `C:\BookingsAssistant`
   (on GitHub: **Code > Download ZIP**).
2. **Double-click `setup.bat`.** No admin rights needed. It:
   - installs Python 3.13 if this computer doesn't have 64-bit Python 3.12/3.13
     (with winget, or from python.org after checking the installer's signature),
   - installs the app's libraries into a private `.venv` folder,
   - downloads ADOMD.NET (the connector for the live server, like Excel uses),
   - creates `.env` and a **Bookings Assistant** desktop shortcut,
   - offers to start the app.
3. **In the app, open Settings** (menu › Admin), create an admin password, then enter:
   - the **Claude API key**, and click **Test Claude**,
   - the **server**, **username** and **password** you use in Power BI/Excel, and click **Test server**.
4. **Open Cubes** (menu › Admin): tick the cubes people should use, then set each one up (below).

Run `setup.bat` again at any time to repair or update the installation; your settings are kept.
If the connection test fails with every setting, `python test_connection.py` (in the folder,
after `.venv\Scripts\activate`) tries other connection options.

## Settings page (keys and passwords)

Open **⚙️ Settings** in the app's menu. The first time, create an **admin password**; do this
before you share the app link. Only admins can change keys and the glossary.

- **Claude API key** and **bookings server login**: paste them in and click Save. They are stored
  in Windows Credential Manager (macOS: Keychain), never in a text file, and never shown again.
  Saving the API key here also removes any plain-text copy from `.env`.
- **Test Claude** / **Test server** check that they work.
- Forgot the admin password? Run `python reset_admin_password.py`, then create a new one.
  Saved keys and passwords are kept.

## Cubes page: connect and set up cubes (admins)

**Connected cubes:** the page lists every cube on the server your login can open; tick the ones
people should use. Each connected cube appears in the **Data** picker in Chat and the Glossary.

**Set up a cube** (once per cube, about 5 minutes):
1. **Read the structure and values** - every measure, column and value, with how much data each has
   (about a minute). Do it again after the cube changes.
2. **Map the business words** - Claude works out what words like *bookings*, *sales*, *destination*
   or *valid bookings* mean in this cube.
3. **Answer a few questions** in plain words, e.g. *"When you ask for bookings in March, which date
   do you mean? The day the booking was made / The day the guest travels"*. Not sure? Skip it; Chat
   asks whoever needs it.
4. **Confirm what Claude understood** about everything else (untick anything wrong).

Answers become the cube's **Glossary** - the agreed meaning Claude follows for every question.

## Glossary page (what the words mean)

Open **Glossary** (menu › Ask) and pick a cube. It shows each business word and what it means in
the data. **Agreed** terms are always followed; **Draft** ones make Claude ask or say what it
assumed. Admins can edit terms at the bottom of the page. Each cube has its own glossary and its
own notes (`models/<cube>/notes.md`) for hints Claude reads with every question.

If something goes wrong, the app shows a plain-English message; the technical text is under
**Technical details (for support)**.

## Daily use

Windows: double-click the **Bookings Assistant** desktop shortcut (or **`run_app.bat`**).
Mac: run `bash run_app.sh` in Terminal. Your browser opens at http://localhost:8501.

### Dashboards (open first)

Every dashboard is listed under **Dashboards** in the menu. Headline numbers at the top (with the
change vs the same period last year), then charts. A dashboard can mix charts from different cubes.
Pick a **Period** (last 7 days, this month, last month, this year, last 12 months or a custom range)
and every chart follows it. **Refresh** gets the latest numbers; it never uses Claude, it just
re-runs the saved queries.

Admins (signed in with the admin password) use the **⋯** menus:
- next to Refresh: **Add chart** (describe it in plain English), **New dashboard**, **Rename**,
  **Delete dashboard**;
- on each chart: **Edit** (title, chart type, size, which date the period applies to, the question
  or the query), **Send to another dashboard** (copy or move), **Move earlier/later**, **Delete**.

An empty dashboard offers **Create suggested charts** from a set-up cube. Dashboards are saved in
`dashboards.json`.

**Charts** are chosen to fit the data: a **world map** when the breakdown is by country, **line** or
**area** for trends, **donut** for a few parts of a whole, **treemap** for many parts, **bars** for
rankings, **stacked columns** or a **heatmap** for two breakdowns, **scatter** for two numbers. You can
always pick another type when editing a chart.

### Chat

Pick the cube in the sidebar (**Data**), then type a question or click one of the suggested
questions, e.g.:
- *Bookings by month for 2026*
- *Top 10 destinations by revenue this year*
- *Compare this month with the same month last year by channel*
- Follow-ups work: *now only for Spain*, *show it as a table*

Claude first shows **"I understood your question as: ..."** (the exact measure, dates and
filters) so you can check it. If the question is too unclear to answer, it asks you instead,
with one-click answers. **Hover over any chart** and click **Add to dashboard** to send it to any
dashboard, or a new one (admins only); on the dashboard it then follows the dashboard's period.

**Claude checks the data before writing the query.** Setting up a cube also builds a local index
of every value in every text column (statuses, markets, countries, customers, suppliers...) with how
much data each has, saved in `models/<cube>/value_index.json` (not in git). Before answering, Claude
looks up the words in your question in that index (you see each check, e.g. *Looking up "UAE"*) and can
test-run a query. If a word matches different things (e.g. Market "UAE" vs agency country "UNITED ARAB
EMIRATES") or a value nobody uses, it asks you, with the real values as options. As a final safety net,
every value a query filters on is checked against the data before it runs. Answers take about 15-35
seconds. Business words like "Ok bookings" belong in the Glossary; once a term is Agreed there, Claude
stops asking about it.

Under each answer you can open the **data** (and download it as CSV) and the **query**
Claude wrote (DAX in live mode, SQL in local mode), so you can check it.

Every answer is saved automatically:
- `data/results/` - one CSV per question
- `data/history.jsonl` - question, DAX, and summary log (also shown in the sidebar)

## Scheduled pulls (optional, Windows live mode)

1. In the app, under an answer, open **DAX query** and click
   **Save this query for scheduled pulls**. It's saved in `queries/`.
2. Open **Task Scheduler** > **Create Basic Task** > choose a time (e.g. daily 07:00) >
   **Start a program** > browse to `run_pull.bat`.
3. Fresh data lands in `data/snapshots/` (latest copy + a dated copy each run).
   Results and errors are logged in `data/pull_log.txt`.

You can point Excel or Power BI at those CSVs, or ask the app new questions any time.

## Troubleshooting

| Problem | Fix |
|---|---|
| `ADOMD.NET was not found` | Run `setup.bat` again (it downloads ADOMD.NET), or install the ADOMD MSI from https://learn.microsoft.com/analysis-services/client-libraries. If installed somewhere unusual, set `ADOMD_PATH` in `.env` to the folder containing `Microsoft.AnalysisServices.AdomdClient.dll`. |
| Connection refused / timeout | Connect to the company network or VPN. Check Excel can still refresh from the same server. |
| Access denied / login failed | On ⚙️ Settings, check the username matches what you type in Excel (including the `DOMAIN\` part) and re-enter the password. Your account needs read permission on the model. |
| `No password saved for ...` | Enter the password on ⚙️ Settings. |
| `pythonnet` / `clr` errors | Delete the `.venv` folder and run `setup.bat` again (it uses 64-bit Python 3.12 or 3.13). |
| Wrong measure or column picked | Add a line to `business_notes.md` explaining what you meant. |
| Cube changed (new measures, columns or values) | Cubes page › select the cube › **Read again**. |
| Mac: `python3: command not found` or a prompt to install developer tools | Install Python from python.org (Mac setup step 1), then open a new Terminal window. |
| Mac: "No data files found" | Put at least one CSV/Excel file in `data/local`. |
| Mac: can't see `.env` in Finder | Files starting with a dot are hidden. Use `open -e .env` in Terminal, or press Cmd+Shift+. in Finder. |
| Answers too slow / costly | Keep `claude-sonnet-5-5`; for simple questions you can try `claude-haiku-4-5-20251001` in `.env`. |

## Files

| File | What it does |
|---|---|
| `app.py` | The web app's menu: Dashboards, Ask (Chat, Glossary), Admin (Cubes, Settings) |
| `dashboard_view.py` | A dashboard page (each dashboard is a page in the menu) |
| `views/` | The Chat, Glossary, Cubes and Settings pages |
| `cubes.py` | Which cubes are connected, and each cube's folder in `models/` |
| `cube_setup.py` | Setting up a cube: Claude's map of the business words, the questions, the answers |
| `.streamlit/config.toml` | The look: Inter font, Apple-like colours, light and dark themes |
| `dashboards.py` | Dashboards: saved charts (each with its cube), periods, running and building charts |
| `ui.py` | Small pieces of UI shared by the pages, and the Apple-like styling |
| `value_index.py` | Local index of every value in the data (built on Refresh data structure) |
| `data_tools.py` | Read-only tools Claude uses to check the data before writing a query |
| `value_check.py` | Checks the values a query filters on against the real data before it runs |
| `secrets_store.py` | Saves keys and passwords from the Settings page in Windows Credential Manager |
| `admin.py` | Admin sign-in for Settings and glossary editing |
| `glossary.py` | Each cube's glossary (its agreed map of business words), passed to Claude |
| `errors.py` | Turns errors into plain-English messages |
| `reset_admin_password.py` | Removes a forgotten admin password |
| `llm.py` | Prompts Claude: question to DAX or SQL, result to chart + summary |
| `backends.py` | Picks live mode (Windows) or local mode (Mac) |
| `ssas.py` | Live mode: connects to Analysis Services, runs queries, reads the model structure |
| `localdb.py` | Local mode: loads files from `data/local` and runs SQL on them |
| `test_connection.py` | Live mode: finds connection settings the server accepts |
| `charts.py` | Picks the best-fitting chart (map, trend, donut, treemap, heatmap...) and draws it |
| `storage.py` | Saves results and history |
| `build_schema.py` | Tests the connection and writes `schema.md` |
| `pull.py` | Re-runs saved queries for scheduled refreshes |
| `get_adomd.py` | Backup way to get ADOMD.NET without the installer |
| `set_password.py` | Saves your server password securely in Windows Credential Manager |
| `setup.bat` / `run_app.bat` | Windows setup (runs `setup_windows.ps1`) and start |
| `setup.sh` / `run_app.sh` | Mac setup and start |
| `.env` | Your settings and API key (keep private, don't share or email it; delete it before sending the folder to someone) |
| `business_notes.example.md` | Template for each cube's notes (`models/<cube>/notes.md`) |
| `.gitignore` | Keeps secrets and company data (`.env`, `models/`, `dashboards.json`, results) out of Git |
