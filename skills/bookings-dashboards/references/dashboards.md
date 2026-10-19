# Designing a dashboard

A dashboard is read top to bottom by busy people: what happened (headline numbers), how it moved (the trend),
who and what drove it (rankings and shares), then the detail (demand, conversion, tables).

## Order

1. **Headline numbers** - 4 or 8 `kpi` charts (they sit in rows of four): money first (sales, profit, margin),
   then volume (bookings, room nights), reach (active clients) and demand (searches, look-to-book).
2. **The trend** - one `line` at `full` width of the main measure by day.
3. **Who buys** - top clients, markets (`horizontal_bar`, top 10, `half`), a `map` of countries (`full`).
4. **What is bought** - destinations, hotels, suppliers, channels; shares as `donut` (few parts) or `treemap`.
5. **Demand and conversion** - searches, API requests, look-to-book, failures.
6. **Detail tables** - at the end, `full` width.

Two `half` charts side by side should belong together (e.g. top clients and top markets). Put new charts where
they fit this order (`add_chart` with `position`, or `move_chart`), not always at the end.

## Titles and descriptions

- Titles say what is shown, without dates: "Sales by destination", "Top 10 clients". The dashboard shows the
  period.
- `question` explains the number in a sentence a manager understands, including what is left out: "Sales in AED,
  net of cancellations; test agencies left out."

## Filters (a client, market, destination or supplier view)

`set_dashboard_filters` adds pickers above a dashboard. Each filter has a key (`client` → `@F_CLIENT` in the
queries), a label, and a query listing the values to pick from - those with data in the last year (it runs with
`@START` / `@END` over the last year), biggest first, so the first is the default:

```json
[{"key": "client", "label": "Client",
  "options": {"cube": "<bookings cube>",
              "query": "EVALUATE TOPN(500, SUMMARIZECOLUMNS('Customers'[Code], 'Customers'[Code.Key0], 'Customers'[Customer], 'Customers'[Customer.Key0], <period filter>, \"Sales\", [Sale]), [Sales], DESC) ORDER BY [Sales] DESC",
              "value": "Code", "label": "{Customer} - {Code}"}}]
```

Then every chart on that dashboard filters with the placeholder. A good start for a view of one client, market
or destination: `copy_dashboard` an existing view and change it.

## Built-in dashboards

The app ships with a business overview and market, destination, client and supplier views. They are good
examples (`get_dashboard`). New app versions update them until someone changes their charts or filters; then
the dashboard belongs to the user and stays as they leave it.

## Checklist before saving

- Ran with `run_query`; the numbers look plausible (compare with a headline number already on the dashboard).
- `x` / `y` / `color` are exact result columns; every number column has a format.
- The date follows `@START` / `@END`; test data is left out like the other charts on the dashboard.
- Placed in reading order; the title has no dates.
