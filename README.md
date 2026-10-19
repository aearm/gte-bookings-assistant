# Bookings Assistant

Ask questions about your Analysis Services cubes in plain English and get the best-fitting chart
(world map, trend, donut, treemap, heatmap...) or exactly the chart you describe, a short written
answer, and the data. Claude works from one **data layer** that covers every cube, so it picks the
right cube itself and can combine several cubes in one answer (e.g. sales from Bookings next to
payments from Booking Payments, per customer). Keep useful answers on named dashboards. Admins
connect the cubes and build the data layer once after installing.

The app has two modes and picks one automatically:

| | **Live mode** (Windows) | **Local mode** (Mac, or any computer) |
|---|---|---|
| Data | The cubes on your Analysis Services server (chosen on the **Cubes** page) | CSV / Excel files in `data/local` (sample data included) |
| Claude writes | DAX | SQL |
| Needs | ADOMD.NET + server login | Nothing extra |

```
Data layer (built once): every cube's structure + values -> Claude's profile of each cube
                         -> shared dimensions (customer, supplier, hotel...) measured on the values

Your question  ->  Claude Haiku makes it a standalone question; code works out its dates
               ->  Claude reads the data layer, checks values, writes a plan:
                   one query per cube (+ SQL joining them when several cubes are needed)
               ->  runs on the live cubes or local files  ->  results saved as CSV
               ->  Claude picks a chart (or draws the one you described) + writes the answer
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
   bash install/setup.sh
   ```
5. **Add your API key:** run `open -e .env`, paste the key after `ANTHROPIC_API_KEY=`, save.
6. **Start the app:**
   ```
   bash install/run_app.sh
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

1. **Download `install-bookings-assistant.cmd`** from the latest release on GitHub (**Releases**, under
   **Assets**) and **double-click it**. Nothing to answer, no admin rights needed. (Windows may first ask
   whether to run a downloaded file: click **More info › Run anyway** or **Run**.) It:
   - downloads the app into `%LOCALAPPDATA%\Programs\Bookings Assistant`,
   - installs Python 3.13 if this computer doesn't have 64-bit Python 3.12/3.13
     (with winget, or from python.org after checking the installer's signature),
   - installs the app's libraries into a private `.venv` folder,
   - downloads ADOMD.NET (the connector for the live server, like Excel uses),
   - creates `.env` and a **Bookings Assistant** desktop shortcut,
   - starts the app in the background whenever you sign in to Windows, starts it now and opens
     http://localhost:8600 in the browser.

   Already have the app's folder (a release zip, unzipped, or a `git clone`)? Double-click the
   **`install-bookings-assistant.cmd`** in it instead: it does the same, in that folder. In a copy without
   the built web app (a clone), setup also builds it, downloading Node.js for this user first if the
   computer doesn't have it. The rest of the setup scripts are in the folder's `install\`.

   The five built-in dashboards are there at once; their numbers appear as soon as the server is entered
   in Settings (step 2).
2. **In the app**, create the admin password, then open **Settings** (menu › Admin) and enter:
   - the **Claude API key**, and click **Test Claude**,
   - the **server**, **username** and **password** you use in Power BI/Excel, and click **Test server**.
3. **Open Cubes** (menu › Admin): every cube on the server is connected until you tick the ones people
   should use. Click **Build the data layer** (once; about a minute per cube) so questions can be asked.
   Or run `python build_layer.py --all`.

Run the installer again at any time: an installation older than the latest release is updated to it first
(settings, keys, dashboards and data are kept), then repaired and started. Options, from a
command prompt in the app folder: `install-bookings-assistant.cmd -NoAutostart` (start it now but not
with Windows), `-NoStart`, and `-Classic` for the previous app (Streamlit, port 8501).

### Updating to a new version

Double-clicking the installer again updates an installation to the latest release (see above). Admins can
also update the app from inside it: **Settings › App version › Check for updates**. If GitHub has a
newer release you see its number, date and what's new, and **Update to …** does the rest: it downloads
the release, the app stops, the new code is put in place (new libraries are installed if needed), and
the app starts again by itself - about a minute; the page reconnects when it's back. Users don't
need to do anything.

An update never touches what belongs to your installation: settings and keys (`.env`, Windows
Credential Manager), dashboards (`dashboards.json`), the data layer and value lists (`models/`), answer
memory, usage, results and history (`data/`), the glossary and saved queries, and the Python
environment (`.venv`). The current version is saved in `data/backup/` first; if any step fails the
previous version is put back and started, and Settings says what went wrong. A copy made with
`git clone` (a developer copy) is updated with `git pull` instead, then a restart of the app.

**Releasing a version** (for the maintainer): `main` always carries the latest release. Put the new
number in `VERSION` (e.g. `2.0.1`), add its section to `CHANGELOG.md` (what changed: admins read it before
updating), commit and push to `main`. GitHub then publishes release `v2.0.1` by itself
(`.github/workflows/release.yml`): it builds the web app and attaches the full app
(`bookings-assistant-2.0.1.zip`) and the one-click installer, which from then on installs that version.
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

## The data layer (built once)

Before Claude answers anything it reads **one layer that describes all the data**, built once after
installing (Cubes page › **Build the data layer**, or `python build_layer.py --all` in the app folder).
It follows the usual layering of a semantic model:

1. **Physical layer** - every cube's exact measures, columns and helper columns, and every value of every
   text column with how much data it has (`models/<cube>/schema.md`, `value_index.json`, and
   `models/values.db` for big columns).
2. **Semantic layer** (`models/data_layer/layer.json`) - for each cube, Claude's profile: what it is for,
   its grain (what one row is), its measures with business names, synonyms, units and whether they can be
   added up, what each date means, the business entity of each dimension (customer, supplier, hotel...)
   and common filters. Across cubes: the **shared dimensions** (a bus matrix) with the join column in
   each cube, chosen from how well their **values actually match** (measured, not guessed from names),
   and which cube to use for which topic. Every name in it is checked against the real cube.
3. **Index cards and a graph** - a few lines per cube (what it's for, its measures, dates and dimensions:
   about 7,000 tokens for all 27 cubes) and the links between cubes (shared dimensions, join columns,
   match quality). This is what Claude reads with every question (`routing.py`).

How a question is answered, quickly and cheaply:
- **Prepare the question** (`rewrite.py`): Claude Haiku turns a follow-up ("and by market?") into a
  standalone question with everything it depends on, sets apart how to draw it, and describes each
  period ("last month", "week 41", "H1 2019") in a small grammar that **code** turns into exact dates.
  The planner gets the standalone question and those dates, not the conversation. A message that only
  asks to show the last answer differently ("as a pie") is redrawn without planning.
- **Pick the cubes**: Claude Haiku (fast, cheap) reads the cards and picks the cube(s) the question needs;
  the words of the question are also looked up as exact values in every cube ("UAE" -> Market = "UAE").
- **Plan**: Claude Sonnet gets every cube in one line, the picked cubes' details (the columns and measures
  their meaning layer names - a third of the full structure, which it can still read with a tool), how
  they join, the values found and verified examples - so it rarely needs extra rounds. The rules and the
  cube list are cached for an hour; a cube's details for 5 minutes on a first question about it, and for
  an hour once it is asked about again (the cubes always in the same order, so the next question reads
  them for a twentieth of the price). A new question is prepared and its cubes picked at the same time.
  Planning runs at medium effort (`CLAUDE_PLAN_EFFORT`).
- **Checks in code before anything runs**: every table, column and measure must exist in its cube (a
  misspelt name goes back to Claude with the closest real one), hidden measures are refused, the dates
  filtered must be the question's dates, and filter values must be in the data. A plan that returns no
  rows gets one more look (wrong value format, wrong date, a join that matches nothing).
- **Chart**: standard charts are formatted by Claude Haiku (`CLAUDE_FAST_MODEL`); charts described in words
  by Claude Sonnet.
- **Answer memory** (`data/answers.db`): the same question again on the same day reruns its saved plan,
  with no Claude call (and no chart call when the numbers are unchanged). Admins can **Mark as correct**
  under an answer; marked answers are given to Claude as examples for similar questions.

Each cube is a separate Analysis Services database, so a question that needs two cubes becomes one
DAX query per cube, run in parallel and joined in memory on a shared dimension (aggregated to the same
grain first, full outer join so nothing is dropped, ratios computed after the join). The query box
under each answer shows every step and the joining SQL. For "the top 10 customers with their X from
another cube", a small first step finds the 10 and the other cubes are asked only about them
(`@KEYS(top, Code)` in a step is replaced with the codes that step returned): 10 customers read instead
of all of them (a dashboard chart went from 31 s to 6 s). A step that is joined is never cut short:
above `STEP_MAX_ROWS` rows (100,000) the plan fails and Claude aggregates it instead.

Run it again after cubes change: the Cubes page says which cubes are new or changed, and **Update new
and changed cubes** only asks Claude about those. The layer is built with `CLAUDE_LAYER_MODEL`
(default `claude-opus-5-5`); questions use `CLAUDE_MODEL`.

## The meaning layer (ships with the app)

On top of the data layer, `semantic/` holds **what every number means**, built once from the real
cubes and shipped with each release, so a new installation is ready without building it:

- **One measure per business word.** 562 terms, each pointing to exactly one measure of one cube
  ("searches" → Statistics Zone `[Total Requests]`, never "hotels requested"; "sales" → Bookings `[Sale]`).
  Words found in a question are matched in code and given to Claude as facts, like values ("UAE").
- **A default date per cube**, the words that pick another one ("created", "travel", "stay"), and the months
  each date has data for.
- **Measures that must never be used** (last-year helpers, duplicates, broken or empty ones) - a query that
  uses one is refused before it runs - plus each measure's unit and whether it can be added up (ratios and
  averages never are).
- **Data coverage**: cubes with no data are never picked; historical cubes (tickets, relocations) and recent
  ones (statistics) say which periods they cover.
- **The helper columns** each breakdown needs: added to every query automatically.
- **Named filters** ("owned hotels", "cancelled bookings", "UAE market") with their exact stored values,
  and rules per cube.

How it was built: facts were read from every cube by code (`python semantic.py facts`: which measures have
data, the months each date covers, the helper columns), the meanings were drafted by Claude Opus at its
highest effort from those facts, and every claim was checked against the cubes again
(`python semantic.py check`; `python semantic.py build` writes the shared files). The checks also found
problems in the cubes themselves - e.g. supplier error counts overflow above 2.1 billion (ask per month),
swapped markup and margin measures, response times stored 1000 times too small - which the files explain.

**Decisions only a person can make** (51, e.g. *does "sales" mean Sale or Final Sales?*) come with a
proposed answer, which is used until an admin agrees on the **Glossary** page › **Decisions**. Agreed
answers are kept in `data/semantic_overrides.json`, so updates never overwrite them. No customer, hotel,
supplier or person names are in `semantic/`; actual values stay in each installation's value index.

## Cubes page: connect cubes and build the data layer (admins)

**Connected cubes:** the page lists every cube on the server your login can open; tick the ones
people should use. Each connected cube appears in the **Data** picker in Chat and the Glossary.

**Data layer:** build it once (see above); the page shows when it was built, which cubes are in it,
and what Claude knows (shared dimensions, which cube for what, the catalog).

**Business words of a cube** (optional, once per cube, about 5 minutes):
1. **Read the structure and values** - every measure, column and value, with how much data each has
   (about a minute; building the data layer does this for every cube).
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
assumed. **Decisions** lists the meaning layer's open questions for that cube with the proposed answer;
admins choose and click **Agree**. Admins can edit terms at the bottom of the page. Each cube has its own glossary and its
own notes (`models/<cube>/notes.md`) for hints Claude reads with every question.

If something goes wrong, the app shows a plain-English message; the technical text is under
**Technical details (for support)**.

## Daily use

Windows: double-click the **Bookings Assistant** desktop shortcut. It opens http://localhost:8600 in the
browser, starting the app first if it isn't running (**`install\run_app.bat`** does the same and keeps a
window with the app's messages). Mac: run `bash install/run_app.sh` in Terminal; your browser opens at
http://localhost:8501.

### Start automatically with Windows

Setup does this. The app then starts in the background, without a window, whenever you sign in to
Windows, and restarts by itself if it stops. Its messages go to `data\api.log`. To change it, run
**`install\install_autostart.ps1`** in PowerShell, in the app folder, with an option:
- **On a server nobody signs in to** (e.g. after Windows updates restart it): run
  `install\install_autostart.ps1 -AtStartup`. It starts when the computer starts, before anyone signs in;
  Windows asks for your account password once to store it with the task (the app needs your account
  because the keys and passwords are in your Credential Manager).
- To restart it: `install\install_autostart.ps1` again (or Task Scheduler › Bookings Assistant › End, then Run).
- To stop starting automatically: `install\install_autostart.ps1 -Remove`.
- The previous app (Streamlit, http://localhost:8501, messages in `data\app.log`):
  `install\install_autostart.ps1 -Classic`.

### Dashboards (open first)

Every dashboard is listed under **Dashboards** in the menu. Headline numbers at the top (with the
change vs the comparison period), then charts. A dashboard can mix charts from different cubes.
The **period button** above the charts (e.g. *This year · 1 Jan – 13 Oct 2026 · W1–42*) opens a calendar,
and every chart follows what you pick:
- **Quick choices** on the left - today, yesterday, this/last week, last 7 or 30 days, this/last month,
  this/last quarter, this/last year, last 12 months (one click);
- **Days** - click a day, then another, on the two months shown;
- **Weeks** - each row starts with its ISO week number (weeks start on Monday; week 1 holds the year's
  first Thursday): click it for that week, shift-click another to add weeks; or type a year and week
  numbers at the bottom (e.g. 2025, weeks 10 to 12);
- **A month** - click the month's name.
Then **Apply**. Every chart follows these dates, unless it keeps a period of its own (see
[Chart periods](#chart-periods)).

A dashboard opens with the numbers each chart had the last time it ran (saved in `data/dashboard_results/`),
so it doesn't wait for the cubes. A chart is run again only when one of its cubes has new data since (the
server's last update time, checked every 5 minutes) or its numbers are a day old - in the background,
the page updating itself when the new numbers are in. **↻** next to the period runs every chart again now.

**Compare** (next to the period, e.g. *vs 1 Jan – 15 Oct 2025*) sets one comparison for the whole
dashboard: **previous period** (the default; the same days of the previous week, month, quarter or year -
"this month" 1-15 Oct is compared with 1-15 Sep - or the days just before), **same period last year** (for
weeks, the same week numbers), **other dates**, or **no comparison**. Each choice shows its dates.
Headline numbers show the change (*+12.3% vs last year*); columns, bars and lines of one measure show the
other period in grey beside this one (both named by their dates in the legend, the change on hover);
tables get a change column after each measure. Maps, donuts and charts of several measures show this
period only. An admin can switch the comparison off for one chart (**⋯ › Edit**).
**Refresh** (↻) gets the latest numbers; it never uses Claude, it just re-runs the saved queries.

**+ Add chart** (top right, and the dashed tile after the charts) and the **+** next to **Dashboards** in
the menu (a new dashboard) are there for everyone; dashboards are shared, so the dialog asks for the admin password first if you
aren't signed in. Admins also have **⋯** menus:
- next to + Add chart: **New dashboard**, **Rename**, **Delete dashboard**;
- on each chart: **Edit** (title, chart type, size, which date the period applies to, the question
  or the query), **Change how it looks** (describe any chart), **Send to another dashboard** (copy or
  move), **Move earlier/later**, **Delete**.

A chart can use **All data** (Claude picks and combines cubes; each cube's main date follows the period).
Chart type **Custom** draws the chart you describe in words (see Chat).

An empty dashboard offers **Create suggested charts** from a set-up cube. Dashboards are saved in
`dashboards.json`.

**Every chart is formatted by Claude for its data before it's drawn**: money with its currency and in
compact form when large (AED 4.5M), percentages as %, counts with thousands separators, axis titles with
units, rankings sorted biggest first, values written on bars when there are few, a legend only when
there are several series. Claude decides this from the numbers' ranges, the query and what each
measure is in the data layer; headline numbers and data tables use the same formats.

**Charts** are chosen to fit the data: a **world map** when the breakdown is by country, **line** or
**area** for trends, **donut** for a few parts of a whole, **treemap** for many parts, **bars** for
rankings, **stacked columns** or a **heatmap** for two breakdowns, **scatter** for two numbers. You can
always pick another type when editing a chart. Several measures of different size (requests in millions,
bookings in tens, sales in AED) get **one panel each**, sharing the categories; ask for them **in one
chart** (*"6 bars for each customer, 3 for each day"*) and they stand side by side, up to three, each on
its own axis in its own colour, the second breakdown in shades of that colour.

### The dashboards the app comes with

Five dashboards come with the app, written by hand on the Bookings, Hotel Sales (owned and third-party
hotels), Searches (Statistics Zone), Client API requests (Statistics History Client), Supplier requests
(Statistics History Supplier), Hotel-level client requests (Statistics Hotel Client) and Hotel Locks
History cubes - no Claude key needed. Every installation has them, first in the list, as soon as the app is
installed, and the overview opens the app; until the server is entered in Settings (or when the installation
reads local files) one note at the top says so. Every chart follows the period and the comparison
picked at the top; the test agencies' market is always left out. Read each one top to bottom: the
headline numbers, the trend, who buys, where the guests go, what is bought, then demand and look-to-book.

Three countries, three different things:
- **market** - where the client (the agency) is based: 'Customers'[Customer Country];
- **guest nationality** - the guests' nationality, as the agency sent it with the booking:
  'Countries'[Country] in Bookings and Hotel Sales (a UAE agency booking Turkish guests counts under
  Turkey). Always filled; about 15% of bookings come from agencies that send the same value for every
  booking (usually their own country), which is a default rather than a nationality;
- **destination** - where the guests stay: the hotel's country and city ('Hotels'[Hotel Country] and
  [Hotel City] in Hotel Sales, which holds every hotel booking; Bookings has only 'Areas', which mixes cities,
  regions and countries). Destinations are about hotel bookings.

- **Business overview** - for the executives: sales, profit, margin, bookings, room nights, active
  clients, searches and look-to-book (API requests per booking; lower is better, so a fall shows green);
  sales, profit and bookings over time; the top client countries and clients; guest nationalities; sales by
  channel; where the guests stay (map and top 10 destinations); the top suppliers with their margin; the
  booking window; confirmed and cancelled bookings; searches and look-to-book over time; and the clients that
  search most next to what they book.
- **Market view** - pick a market (the agencies' country, e.g. Saudi Arabia): its headline numbers and
  trend, the clients driving it (grey bars: the comparison period, so growing and shrinking clients stand
  out), who travels (the guests' nationalities) and where they go (destinations), top hotels, its top clients' searches next to their
  bookings, searches over time, channels, booking window and cancellations. With the comparison on, this
  answers "why is this market up or down".
- **Destination view** - pick a destination (the hotel's country, e.g. Turkey): its hotel sales, profit,
  margin, bookings, room nights and clients; the hotel requests clients send for it and the share answered
  with availability (how well it is supplied); its top cities, who travels there (the guests' nationalities)
  and where they are booked from (the agencies' countries), the clients selling it, top hotels, the supplier connections behind it, hotel locks there by
  reason, booking window, cancellations and channels.
- **Client view** - pick a client (the clients with sales in the last year, biggest first; type to
  search): its headline numbers (with the average booking value), sales, bookings and API requests over
  time, where its guests stay and their nationalities, the suppliers that served it, its top hotels,
  cancellations, booking window, how its API requests were answered, and the API's response time for it.
- **Supplier view** - pick a supplier connection (the supplier connections with sales in the last year,
  biggest first): the sales, profit, margin and bookings made through it next to what we ask of it - the
  requests the engine sends it, their look-to-book, its response time and its hotel locks (options that
  failed when rechecked: lost bookings; all three better lower); requests and response time over time, how
  it answered (correct, no results, errors), why its hotels locked and where, the clients booking through it
  and the clients whose searches cost the most requests, where its guests stay, top hotels, cancellations and
  booking window. Suppliers are matched by their connection code, the same in Bookings ('Product
  Type'[Module Code]), Hotel Sales ('Modules'[Module Code]) and the supplier-side cubes.

The value picked is kept in the page address (`?f_market=…`, `?f_destination=…`, `?f_client=…`,
`?f_supplier=…`), so a link opens the same view. A margin's change shows in percentage
points (+3.2 pts). Their definitions are in `builtin_dashboards.py`; a new version of the app may bring a new
version of them, which replaces their charts (a renamed dashboard keeps its name; one deleted is not added
again). Admins can still add charts to them, or make their own dashboards.

### Chat

**Data** in the sidebar is **All data** (Claude picks the cubes, and joins them when needed) or one cube.
Type a question or click one of the suggested questions, e.g.:
- *Bookings by month for 2026*
- *Top 10 destinations by revenue this year*
- *Compare this month with the same month last year by channel*
- *Sales and payments by customer this year* (two cubes, joined on the customer)
- Follow-ups work: *now only for Spain*, *show it as a table*

**Dynamic charts:** ask for any chart in your own words - *as a funnel*, *sales as bars and profit % as
a line on a second axis*, *stacked area by channel as percentages*, *a sunburst of region and country*,
*a waterfall*... Claude writes a chart description (a Plotly figure pointing at the result's columns);
the app checks it and draws it - nothing is executed. A follow-up that only changes the chart reuses the
data, and **Change chart** under any answer redraws it. Described charts can go on dashboards too.

Claude first shows **"I understood your question as: ..."** (the exact measure, dates and
filters) so you can check it. If the question is too unclear to answer, it asks you instead,
with one-click answers. **Add to dashboard** under any chart sends it to any dashboard, or a new one
(admins only), and **Make a dashboard from this conversation** (under a conversation with two charts or
more) puts its charts on a new dashboard of their own and opens it (Claude prepares them at the same
time; one that can't be prepared is reported and the rest are added). On a dashboard a chart follows
the dashboard's dates, keeps the question's own rolling dates, or keeps fixed dates (see
[Chart periods](#chart-periods)); its title drops the question's dates ("Sales by month, 2026" becomes
"Sales by month"). A chart described in words keeps its look.

**What Claude costs** is on the **Settings** page: today, the last 7 days, this month and since
measuring started, by activity (questions, dashboard charts, chart redraws, data layer builds, cube setup)
and by model, from Claude's list prices. Questions answered from memory cost nothing. The exact bill
is at platform.claude.com.

**Claude checks the data before writing the query.** Setting up a cube also builds a local index
of every value in every text column (statuses, markets, countries, customers, suppliers...) with how
much data each has (not in git). Columns with up to 2,000 values (statuses, markets, countries, channels...)
are kept in memory from `models/<cube>/value_index.json`; bigger ones (customers, hotels, zones...) stay on
disk in one SQLite file shared by all cubes, `models/values.db`, where each value is stored once and found
in about a millisecond, so they cost no memory. Columns with more than 20,000 values are searched on the
server when needed. Before answering, Claude
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

### Usage (admins)

**Usage** in the Admin menu shows each question's time, cost, Claude calls, cache use and time per stage
(picking cubes, planning, checks, query, chart), from `data/usage.jsonl`, and the benchmark comparisons.
`python bench.py run <name>` asks a fixed set of 12 real questions (this costs a little) and
`python bench.py compare <before> <after>` shows the difference in time, cost and answers.

**Accuracy test set** (`eval_set.py`, questions in `data/eval/questions.json`, not in git): 60 questions
joining 1 to 5 cubes, with chart requests, reworded versions of the same question, follow-up
conversations, questions whose right answer is a question back, and relative dates ("last month").
Every answer is checked against reference numbers computed from the cubes at the same moment, and its
chart against what was asked. `python eval_set.py run <name> --repeat 3` asks each question 3 times (a
full run costs about $20): the report gives pass rates with their 95% range, which questions passed
every time, where each failure happened (plan, query, cubes, numbers, chart) and the code, prompt and
meaning-layer version tested. `python eval_set.py compare <before> <after>` says which questions got
better or worse and how likely that is to be luck. A third of the questions are marked holdout: they
are not looked at while changing prompts.

### Signed in or not

A pill at the top right of every page says whether you're signed in: amber **View only · Sign in**,
or green **Admin** (click it to sign out). Signing in is one box: the admin password, Enter, done.
**Keep me signed in on this computer** (ticked by default) keeps that browser signed in for 30 days,
until you sign out, or until the admin password is changed (which signs every computer out). Admin pages
show a lock in the menu until you sign in.

## Use it from Claude (no API key needed)

Any Claude conversation on the computer where the app is installed - **Claude Desktop** chats and **Claude
Code** - can use the cubes and the dashboards: ask a question about the data, or say "add a chart of the top 10
destinations by sales to the Market view", and Claude does it with your own Claude, not the app's Claude key.

- **The knowledge is the context.** Claude reads what the app's own Claude reads: the data layer (every cube in
  a card, which cube for what, how the cubes join), each cube's measures, columns and values, the meaning layer
  and glossary, the rules for writing queries, and how the built-in dashboards filter each cube.
- **Drawing is a skill.** The `bookings-dashboards` skill (`skills/bookings-dashboards`) teaches Claude how to
  describe a chart for the app (types, formats, filters, the order of a dashboard). The app then runs the chart
  for whatever period people pick and draws it, like any other.
- **Nothing broken is saved.** Every chart is run on the cubes before it goes on a dashboard; one that fails or
  can't be drawn is refused with the reason, and Claude fixes it. Claude deletes charts or dashboards only when
  asked.
- A built-in dashboard that is changed (from Claude or in the app) becomes yours: new versions of the app no
  longer replace it. To experiment, ask Claude to copy it first.

**Connecting.** Setup does it when Claude Desktop or Claude Code is installed (step 7). By hand, in the app
folder: `.venv\Scripts\python.exe install\connect_claude.py` (`--remove` disconnects). Then quit Claude Desktop
(also from the tray) and open it again. It adds the **bookings-assistant** connector (`mcp_server.py`, which
Claude starts by itself) to Claude Desktop's settings and to Claude Code for every project, and the skill to
Claude Code. Claude Desktop chats get the skill's guide from the connector; to add the skill itself there,
Settings › Capabilities › Skills › upload `data\bookings-dashboards-skill.zip`.

**What Claude can do** (the connector's tools): read the knowledge (`get_knowledge`, `get_cube_details`,
`find_values`, `get_join_path`), run queries (`run_query`), and work on dashboards (`list_dashboards`,
`get_dashboard`, `preview_chart`, `add_chart`, `update_chart`, `move_chart`, `copy_chart`, `delete_chart`,
`create_dashboard`, `copy_dashboard`, `rename_dashboard`, `set_dashboard_filters`, `delete_dashboard`).
It works where the app is installed (the connector runs next to it); Claude on the web (claude.ai in a browser)
can't reach it.

## The new app (React + FastAPI)

A faster app is replacing the Streamlit one: a React front end (`web/`) served by a FastAPI back end
(`server/`), on the same cubes, dashboards, settings and data. Setup installs and starts it (port 8600);
an installation set up before keeps starting the previous app (port 8501) until
`install-bookings-assistant.cmd` is run again in its folder. Both can run side by side. Its API is described in
`docs/api.md`.

**Run it** (in the app folder, after `.venv\Scripts\activate`):
```
python start_api.py
```
and open http://localhost:8600. The server shows the built front end from `web/dist`; build it once, and
again after each change to `web/` (needs Node.js):
```
cd web
npm install
npm run build
```
While working on the front end, `npm run dev` (in `web/`) serves it on http://localhost:5173 with live
reload and sends `/api` to the server on 8600, which must be running.

Environment variables (set before starting it):

| Variable | Default | What it does |
|---|---|---|
| `API_PORT` | `8600` | The new app's port |
| `API_WORKERS` | `6` | Cube worker processes (live mode): cube queries run in them, so pages and queries don't slow each other down. About 130 MB each |
| `APP_DATA_DIR` / `APP_DASHBOARDS_FILE` | `data/`, `dashboards.json` | Another data folder and dashboards file, e.g. throwaway ones for tests (the real ones are never touched) |

At start-up the server connects its workers and reads the data layer, meaning layer and value indexes
into memory. At start-up and every day at 00:05 it runs the dashboard charts for the new day, so the
first visit of the day opens with saved numbers.

### Chart periods

Each dashboard chart either:
- **follows the dashboard's period** (the period button at the top),
- **keeps its own rolling period**, e.g. *yesterday vs the day before*, worked out again every day
  (yesterday stays yesterday), or
- **keeps fixed dates**, which never move.

Pick it when adding a chart, or under **⋯ › Edit**. Adding a chat answer to a dashboard is instant (no
Claude call, no query): the chart is kept as it was seen in Chat - its look, its numbers and (unless it
follows the dashboard) its dates. Only an answer whose query has to be rewritten to follow the dashboard's period waits for Claude (about half
a minute). Both apps work this way.

A dashboard opens on the **last 7 days compared with the 7 days before**. To change that, set
`DEFAULT_PRESET` and `DEFAULT_COMPARE` in `periods.py` (a name from `PRESETS` and a key of
`COMPARE_MODES`); both apps use them, and the nightly run prepares the charts for them.

### Tests of the new app

`python -m pytest` covers the back end too (`tests/test_api.py`). In `web/`:
```
npx vitest run
npx playwright test e2e/app.spec.ts
```
`npx vitest run` tests the front end's own code in seconds. The Playwright test drives the whole app in a
browser (the first time, run `npx playwright install chromium`): it starts its own server on port 8620
from the app's `.venv`, with throwaway data (the real data and dashboards are never touched) and asks Claude nothing. Its test
dashboard runs on the cubes, so it needs the live server.

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
| `ADOMD.NET was not found` | Run `install-bookings-assistant.cmd` again (it downloads ADOMD.NET), or install the ADOMD MSI from https://learn.microsoft.com/analysis-services/client-libraries. If installed somewhere unusual, set `ADOMD_PATH` in `.env` to the folder containing `Microsoft.AnalysisServices.AdomdClient.dll`. |
| Connection refused / timeout | Connect to the company network or VPN. Check Excel can still refresh from the same server. |
| Access denied / login failed | On ⚙️ Settings, check the username matches what you type in Excel (including the `DOMAIN\` part) and re-enter the password. Your account needs read permission on the model. |
| `No password saved for ...` | Enter the password on ⚙️ Settings. |
| `pythonnet` / `clr` errors | Delete the `.venv` folder and run `install-bookings-assistant.cmd` again (it uses 64-bit Python 3.12 or 3.13). |
| Wrong measure or column picked | Add a line to `business_notes.md` explaining what you meant. |
| Cube changed (new measures, columns or values) | Cubes page › select the cube › **Read again**. |
| Mac: `python3: command not found` or a prompt to install developer tools | Install Python from python.org (Mac setup step 1), then open a new Terminal window. |
| Mac: "No data files found" | Put at least one CSV/Excel file in `data/local`. |
| Mac: can't see `.env` in Finder | Files starting with a dot are hidden. Use `open -e .env` in Terminal, or press Cmd+Shift+. in Finder. |
| Answers too slow / costly | Keep `claude-sonnet-5-5`; for simple questions you can try `claude-haiku-4-5-20251001` in `.env`. |

## Files

| File | What it does |
|---|---|
| `app.py` | The web app's menu: Dashboards, Ask (Chat, Glossary), Admin (Cubes, Settings), and the signed-in bar |
| `data_layer.py` | The data layer: reads every cube, Claude's profile of each, shared dimensions measured on the values, the catalog |
| `build_layer.py` | Builds the data layer from the command line (`--all` connects every cube first, `--update` only changed cubes) |
| `answering.py` | Answers a question: pick cubes, plan, check values, run, retry once, chart; reuses today's answers |
| `rewrite.py` | Prepares each message: standalone question, how to draw it apart, periods turned into exact dates by code |
| `routing.py` | Index cards and graph of the cubes; picks the cubes a question needs; finds its values in the data |
| `answer_memory.py` | Remembers answers (SQLite): same-day repeats without Claude, verified answers as examples |
| `usage.py` | Measures each question: Claude calls, tokens, cache, cost, time per stage (`data/usage.jsonl`) |
| `bench.py` | Benchmark: a fixed set of real questions, run and compared between versions |
| `eval_set.py` | Accuracy test set: 60 questions (1-5 cubes, charts, rewordings, follow-ups, ask-back, relative dates), repeated runs with 95% ranges, checked against reference numbers computed at run time (questions in `data/eval/`, not in git) |
| `warm_up.py` | At server start, in the background: the server connector and the value indexes |
| `plans.py` | Query plans: one query per cube, run in parallel, joined in memory with SQL |
| `dynamic_chart.py` | Charts described in words: checks Claude's chart description and draws it |
| `periods.py` | Dashboard periods: quick choices, dates, ISO week numbers |
| `period_picker.py` | The period button and its calendar (quick choices, days, week numbers), and the Compare button |
| `inline_component.py` | Small built-in components (the calendar, "keep me signed in") |
| `dashboard_view.py` | A dashboard page (each dashboard is a page in the menu) |
| `views/` | The Chat, Glossary, Cubes and Settings pages |
| `cubes.py` | Which cubes are connected, and each cube's folder in `models/` |
| `cube_setup.py` | Setting up a cube: Claude's map of the business words, the questions, the answers |
| `.streamlit/config.toml` | The look: Inter font, Apple-like colours, light and dark themes |
| `dashboards.py` | Dashboards: saved charts (each with its cube), periods, running and building charts |
| `ui.py` | Small pieces of UI shared by the pages, and the Apple-like styling |
| `value_index.py` | Local index of every value in the data (built on Refresh data structure): small columns in memory, big ones in `models/values.db` |
| `semantic.py`, `semantic/` | The meaning layer: one measure per business word, default dates, hidden measures, coverage, helper columns, named filters, decisions (see above) |
| `data_tools.py` | Read-only tools Claude uses before writing a plan: a cube's details, finding values in every cube, test-running a query |
| `tests/` | Automated tests (`python -m pytest`; `RUN_LIVE=1` adds tests on the live server and Claude) |
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
| `install-bookings-assistant.cmd` | The one installer (also attached to every release): on its own it downloads the latest release; in an app folder it sets up that folder (nothing to answer) |
| `install/setup_windows.ps1` / `install/run_app.bat` | Windows setup (what the installer runs) and start (`install\run_app.bat classic`: the previous app) |
| `install/install_autostart.ps1` | Start the app automatically with Windows, in the background (Task Scheduler) |
| `mcp_server.py` / `assistant_tools.py` | Claude's connector (MCP): the cubes' knowledge and the dashboards from any Claude conversation, no Claude key of the app's; the work behind each tool |
| `skills/bookings-dashboards/` | The skill Claude follows to describe and arrange dashboard charts |
| `install/connect_claude.py` | Connects the connector and the skill to Claude Desktop and Claude Code (`--remove` disconnects) |
| `updates.py` | Updating from GitHub releases (Settings › App version), keeping all of the installation's data; also the helper that stops, updates and restarts the app |
| `VERSION` / `CHANGELOG.md` | The app's version and what changed in each; raising VERSION on main publishes release `v<VERSION>` |
| `start_server.py` | Runs the previous (Streamlit) app in the background without a window; log in `data/app.log`. Limits numpy's maths library to one thread (it would reserve ~30 MB per CPU core) |
| `builtin_dashboards.py` | The dashboards the app comes with (business overview; market, destination, client and supplier views): their queries and filters |
| `start_api.py` | Runs the new app (FastAPI + the React front end) on port 8600 (`API_PORT`); what Windows starts (log in `data/api.log`). `--open` opens it in the browser, starting it first if needed (the desktop shortcut) |
| `server/` | The new app's back end: the API under `/api` (`docs/api.md`), sign-in, cube worker processes, the nightly chart runs |
| `web/` | The new app's React front end (`npm run build` into `web/dist`, which the server shows) and its tests |
| `install/setup.sh` / `install/run_app.sh` | Mac setup and start |
| `.env` | Your settings and API key (keep private, don't share or email it; delete it before sending the folder to someone) |
| `business_notes.example.md` | Template for each cube's notes (`models/<cube>/notes.md`) |
| `requirements-dev.txt` | Libraries for running the tests |
| `.gitignore` | Keeps secrets and company data (`.env`, `models/`, `dashboards.json`, results) out of Git |

## Tests

```
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest
```

The tests run on small made-up files in a temporary folder (your `models/`, dashboards and data are not
touched) and a scripted stand-in for Claude, so they are free and take seconds. With `RUN_LIVE=1` set,
`tests/test_live.py` also asks real questions on the live server with the real Claude API (this costs
a little and needs the data layer to be built).
