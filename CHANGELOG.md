# What changed

Each version's notes are what admins see in the app (Settings › App version) and on its GitHub release.
To release: raise VERSION, add its section here, commit and push to main. GitHub publishes it by itself.

## 2.1.0 - 2026-10-19

- Use the app from any Claude conversation (Claude Desktop, Claude Code) with no Claude key of the app's: a
  connector gives Claude the cubes' knowledge (the data layer, each cube's details and values, the rules for
  writing queries) and the dashboards, and the bookings-dashboards skill teaches it to draw charts for them.
  Ask for a chart and Claude adds it; every chart is run on the cubes before it is saved. Setup connects it
  when Claude is installed (restart Claude Desktop afterwards); run the installer again on an installed
  computer to connect it there.
- A built-in dashboard whose charts or filters are changed is kept as it is by new versions of the app.
- Changes to dashboards from several programs at once (the app, the previous app, Claude) can no longer
  overwrite each other.

## 2.0.2 - 2026-10-19

- Double-clicking the installer on a computer that already has the app now brings it up to the latest
  version (settings, keys, dashboards and data are kept), then repairs and starts it. Before, it only
  repaired the version that was there, so an older installation never got the built-in dashboards.
- Every installation has the five built-in dashboards, also one that reads local files (each says it
  needs the cube server). The previous app (Streamlit) shows the same note instead of errors.
- Setup removes the setup files from before 2.0.1 left next to the app.

## 2.0.1 - 2026-10-19

- The built-in dashboards are there as soon as the app is installed, without connecting cubes first. Until
  the cube server is entered in Settings, one note at the top says so (no error on every chart).
- Every cube on the server is connected until an admin picks some on the Cubes page.
- One installer: `install-bookings-assistant.cmd`. Downloaded on its own it installs the latest version;
  in an app folder it sets up that folder (it replaces `setup.bat`). The other setup files moved to
  `install/`; an update removes the old ones.
- Releases are published automatically when VERSION changes on main, so the one-click installer always
  gets the latest version.

## 2.0.0 - 2026-10-18

- The new app: a React front end served by a FastAPI back end (http://localhost:8600), on the same cubes,
  dashboards and settings as the previous app, which still runs alongside.
- Dashboards reopen from saved numbers in under a second; charts can follow the dashboard's period, keep
  their own rolling period or show fixed dates.
- Chat answers stream in, and an answer still on its way keeps arriving after leaving the page.
- Five dashboards ship with the app: Business overview, then Market, Destination, Client and Supplier
  views, each with a picker kept in the page address.
- One-click install (`install-bookings-assistant.cmd`) and updates from the Settings page.
