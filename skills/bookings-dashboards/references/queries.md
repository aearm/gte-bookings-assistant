# Queries for dashboard charts

The cubes are Analysis Services multidimensional databases queried with DAX; each cube is a separate database,
so one query reads one cube and a plan joins cubes in DuckDB. `get_knowledge` has the full rules; these are the
shapes that work. Column, measure and table names below are placeholders - take the real ones from
`get_cube_details`, and the proven filters per cube from the knowledge ("How the built-in dashboards filter each
cube").

## The period and business filters

Every step filters its date with the dashboard's period, inside `SUMMARIZECOLUMNS`:

```dax
KEEPFILTERS(FILTER(ALL('Calendar'[Date]), 'Calendar'[Date] >= @START && 'Calendar'[Date] < @END))
```

A column with helper ("group with") columns is filtered and grouped with them next to it - otherwise the server
rejects the query:

```dax
KEEPFILTERS(FILTER(ALL('Customers'[Market], 'Customers'[Market.UniqueName]), 'Customers'[Market] <> "Test market"))
```

## Headline number (kpi)

```dax
EVALUATE SUMMARIZECOLUMNS(<period filter>, <business filters>, "Sales", [Sale])
```

How many members had activity (e.g. active clients):

```dax
EVALUATE ROW("Active clients", COUNTROWS(SUMMARIZECOLUMNS('Customers'[Code], 'Customers'[Code.Key0],
    <period filter>, <business filters>, "n", [Bookings])))
```

## Trend

```dax
EVALUATE SUMMARIZECOLUMNS('Calendar'[Date], <period filter>, <business filters>, "Sales", [Sale])
ORDER BY 'Calendar'[Date]
```

x = `Date` (the column name without the table). Over long periods the app shows weeks or months by itself.

## Ranking (top N)

```dax
EVALUATE TOPN(10,
    SUMMARIZECOLUMNS('Customers'[Customer], 'Customers'[Customer.Key0], <period filter>, <business filters>,
        "Sales", [Sale], "Profit", [Profit]),
    [Sales], DESC)
ORDER BY [Sales] DESC
```

Show names, not only codes. Countries for a map: all of them, no TOPN.

## Ratios

Never add up averages or percentages. Use the cube's own ratio measure when it has one (a margin, look-to-book),
or compute it from summable numbers: `DIVIDE([Profit], [Sale])` in DAX, or in `combine_sql`
`SUM(p."Profit") / NULLIF(SUM(s."Sales"), 0)`.

## Several cubes

One step per cube, each aggregated to the same grain (the same breakdown), joined in `combine_sql` on the shared
dimension's columns (`get_join_path`), text keys compared with `upper(trim(...))`, `FULL OUTER JOIN` + `COALESCE`
to keep members found in one cube only. For a top N across cubes, a first small step finds the top N and the other
steps keep only those with `@KEYS(<step>, <column>)`.

```json
{"steps": [
   {"name": "top", "cube": "<bookings cube>", "query": "EVALUATE TOPN(10, SUMMARIZECOLUMNS('Customers'[Code], 'Customers'[Code.Key0], 'Customers'[Customer], 'Customers'[Customer.Key0], <filters>, \"Sales\", [Sale]), [Sales], DESC)"},
   {"name": "req", "cube": "<requests cube>", "query": "EVALUATE SUMMARIZECOLUMNS('Client'[Customer Code], 'Client'[Customer Code.Key0], <filters>, KEEPFILTERS(FILTER(ALL('Client'[Customer Code], 'Client'[Customer Code.Key0]), 'Client'[Customer Code] IN @KEYS(top, Code))), \"Requests\", [Total Requests])"}],
 "combine_sql": "SELECT t.\"Customer\" AS \"Client\", t.\"Sales\", r.\"Requests\" FROM top t LEFT JOIN req r ON upper(trim(t.\"Code\")) = upper(trim(r.\"Customer Code\")) ORDER BY t.\"Sales\" DESC"}
```

A step's result columns: a grouped column by its column name without the table (`'Customers'[Code]` → `"Code"`),
a measure by the label given in the query.

## Dashboard filters

A dashboard with a filter (e.g. a client picker) has a placeholder in its charts' queries, filled with the
picked value as quoted text:

```dax
KEEPFILTERS(FILTER(ALL('Customers'[Code], 'Customers'[Code.Key0]), 'Customers'[Code] = @F_CLIENT))
```

When a filter means the same thing in another cube under another column or spelling, map it there (the
knowledge shows how the built-in dashboards do it per cube).
