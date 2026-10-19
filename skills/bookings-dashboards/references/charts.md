# Describing a chart

What `add_chart`, `preview_chart` and `update_chart` take. The app draws it exactly like this.

```json
{
  "title": "Top 10 clients",
  "question": "The 10 clients with the most sales in the period, with their profit.",
  "chart_type": "horizontal_bar",
  "steps": [{"name": "result", "cube": "<exact cube name>", "query": "EVALUATE ... @START ... @END ..."}],
  "combine_sql": "",
  "x": "Client",
  "y": ["Sales"],
  "color": "",
  "width": "half",
  "style": {
    "formats": [{"column": "Sales", "d3_format": "~s", "prefix": "AED ", "suffix": ""}],
    "sort": "value_desc",
    "show_values": true,
    "legend": "none"
  },
  "compare": true
}
```

- `x`, `y`, `color`: exact column names of the result (as `run_query` lists them).
- `width`: `half` (two charts side by side) or `full`. Trends, maps, wide tables and custom charts: `full`.
- `compare`: `false` keeps a chart from ever showing the comparison period (e.g. a ranking table whose own
  numbers are the point). The app shows the comparison on headline numbers, tables, and single-measure bars or
  lines.
- `date_column`: only when the period should apply to another date than the cube's main one.

## Chart types

| type | use for | x / y / color |
|---|---|---|
| `kpi` | one headline number | query returns 1 row, 1 number; no x |
| `line` / `area` | a trend over time | x = date (day, week or month), y = 1-3 measures |
| `bar` | a few categories compared | x = category, y = measure(s) |
| `horizontal_bar` | rankings, top N, long names | x = name, y = measure, sort value_desc |
| `stacked_bar` | a category split by a second one with few values | x, y = 1 measure, color = the split |
| `donut` | 2-6 parts of a whole | x = part, y = 1 measure |
| `treemap` | shares across many parts | x = part (color = parent level, optional), y = measure |
| `map` | anything by country | x = country name, y = measure (all countries, no TOPN) |
| `heatmap` | two breakdowns with many values (market by month) | x, color = the two, y = measure |
| `scatter` | two numbers related | x = number, y = number, color = label (optional) |
| `table` | many numbers per row, or a list to read | y = the number columns shown |
| `custom` | a chart no type above draws (bars + line on two axes, funnel, sunburst, sankey...) | `custom` option |

Several measures of very different size or unit (requests in millions, bookings in tens) are drawn as one panel
each with its own scale; `style.measures = "one_chart"` puts them in one chart, each on its own axis.

## style

- `formats` - one per number column shown: money `{"d3_format": "~s", "prefix": "AED "}` (AED 4.5M) or `",.0f"`
  for small amounts; counts `",.0f"` (`"~s"` in the millions); fractions 0-1 `".1%"`; numbers already 0-100
  `",.1f"` with suffix `"%"`; averages and ratios `",.2f"`; durations with their unit as suffix (`" s"`, `" days"`).
- `sort` - `value_desc` for rankings and categories, `label` for dates and natural orders (bands, stars),
  `none` to keep the query's order.
- `show_values` - true for up to ~12 bars or 7 slices; false for lines, maps and dense charts.
- `label_angle` - 0, -30, -45 or -90 (use `horizontal_bar` instead for long names).
- `legend` - `none` for one series, else `top` (or `right`, `bottom`).
- `x_title` / `y_title` - y: the measure and unit ("Sales (AED)"); empty for donut, treemap, map and when obvious.
- `log_scale` - only when values span orders of magnitude.
- `lower_is_better` - headline numbers that are better when they fall (look-to-book, response time, failures):
  a rise shows red.

## Custom charts (ECharts)

`chart_type: "custom"` with `custom`: an ECharts option whose data point at the result's columns. Nothing in it
runs: no functions, no code in formatter text, no links or images.

```json
{
  "xAxis": {"type": "category", "data": {"col": "Month"}},
  "yAxis": [{"type": "value", "x-format": {"d3": "~s", "prefix": "AED "}},
            {"type": "value", "position": "right", "x-format": {"d3": ".0%"}}],
  "series": [
    {"type": "bar", "name": "Sales", "data": {"col": "Sales"}},
    {"type": "line", "name": "Margin", "yAxisIndex": 1, "data": {"col": "Margin"}}
  ]
}
```

- `{"col": "Name"}` anywhere becomes that column's values; `{"cols": ["A", "B"]}` its rows as `[a, b]` pairs.
- `"split_by": "Channel"` in a series draws one series per value of that column.
- Hierarchies (treemap, sunburst, tree): `{"type": "sunburst", "path": ["Region", "Country"], "value": {"col": "Sales"}}`.
- `"x-format": {"d3": ..., "prefix": ..., "suffix": ...}` on an axis, series or visualMap formats its numbers.
- Optional `"prepare": {"group_by": [...], "aggregate": {"Sales": "sum"}, "sort_by": "Sales", "descending": true, "top": 10}`.
- Series types: line, bar, pie, scatter, effectScatter, radar, tree, treemap, sunburst, boxplot, candlestick,
  heatmap, map, parallel, lines, graph, sankey, funnel, gauge, pictorialBar, themeRiver.
- Don't set fonts, backgrounds or colours unless asked: the app applies its own look (light and dark).
