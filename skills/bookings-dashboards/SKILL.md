---
name: bookings-dashboards
description: Build, add, change and arrange dashboard charts in the Bookings Assistant app from the company's bookings cubes (Analysis Services), through the bookings-assistant connector. Use when the user wants a chart, KPI, dashboard or dashboard change about bookings, sales, profit, clients, markets, destinations, hotels, suppliers, searches or look-to-book - or asks a data question whose answer should be drawn.
---

# Bookings dashboards

The Bookings Assistant app draws dashboards from the company's live cubes and keeps them up to date. Through the
**bookings-assistant** connector you read what is in the cubes, check queries on them, and add or change the
app's dashboard charts. You write the queries and describe the charts; the app runs them for whatever period
people pick and draws them. The app's own Claude is not involved.

## Workflow

1. **Knowledge first** - call `get_knowledge` once per conversation: every cube's card, which cube for what, how
   cubes join, the rules for writing queries, and how the built-in dashboards filter each cube. Then
   `get_cube_details` for each cube you will query (exact measures, columns and helper columns), and
   `find_values` for every name you filter on (a country, client, supplier, status...): filter only on exact
   values found.
2. **Know the dashboard** - `list_dashboards`, then `get_dashboard` for the one to change: its filters, its charts
   (as `add_chart` takes them) and their order. Reuse the style of the charts already there.
3. **Write the query** - one step per cube (most charts have one). The date is filtered with `@START` / `@END`
   (the dashboard's period); a dashboard filter is an `@F_<KEY>` placeholder. Business numbers leave out test
   data the way the built-in dashboards do. Patterns: [references/queries.md](references/queries.md).
4. **Check the numbers** - `run_query` with the steps (dates and filter values optional). Look at the columns it
   returns: `x`, `y` and `color` must be exactly those names. Fix and run again until it is right.
5. **Pick the chart** - the type that answers the question best, with formats for every number:
   [references/charts.md](references/charts.md). `preview_chart` shows how the app draws it without saving.
6. **Save** - `add_chart` (or `update_chart` for a change, `move_chart` for the order). It runs the chart on the
   cubes first and refuses one that fails or can't be drawn - read the answer, fix, retry.
7. **Tell the user** what you added or changed, the first numbers, and the dashboard's link.

For a new dashboard or several charts at once, plan the whole page first:
[references/dashboards.md](references/dashboards.md).

## Rules that matter

- Never guess names: measures, columns and values come from `get_cube_details` and `find_values`.
- Every dashboard chart follows the dashboard's period: each step filters its date with `@START` and `@END`
  (`@END` is the day after the last day). Titles have no dates in them.
- A headline number (`kpi`) is a query returning one row with one number.
- Name things the way the business does (the cube cards and glossary say what each measure means); money is in
  the cube's currency (see its card), e.g. prefix `AED `.
- Three different countries: the client's market (where the agency is), the guests' nationality, and the
  destination (the hotel's country). Use the one the user means; the cube details and knowledge say which
  column is which.
- Change a built-in dashboard only when asked: once its charts are changed it is the user's and app updates no
  longer touch it. To experiment, `copy_dashboard` first.
- Delete charts or dashboards only when the user asked for exactly that.
- When a tool answers with a problem, it says what to fix: fix that and try again rather than guessing.

## Drawing in the conversation

When the user wants to see a chart here (not only on the dashboard), `preview_chart` returns the ECharts
option the app draws. Show it in an HTML artifact with ECharts from a CDN, or draw the `run_query` result
yourself with the same chart type, colours and formats.
