# What changed

Each version's notes are what admins see in the app (Settings › App version) and on its GitHub release.
To release: raise VERSION, add its section here, commit and push to main. GitHub publishes it by itself.

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
