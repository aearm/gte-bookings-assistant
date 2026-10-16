# The meaning layer

What every measure, date and breakdown of the cubes means, which measure answers each business
term, which date a question means by default, what to hide, where the data is, and the rules a
query must follow. Claude reads it before answering; code enforces it (`semantic.py`).

It ships with the app. Admins' own decisions are stored apart (`data/semantic_overrides.json`) and
always win over the shipped files, so updates never overwrite them.

## Files

| File | Holds |
|---|---|
| `cubes/<cube>.json` | One cube: purpose, coverage, dates, measures, breakdowns, named filters, rules, examples |
| `terms.json` | Business term → the one measure that answers it (cube + measure); date words → date role |
| `review.json` | Decisions only a person can make, each with a proposed answer |
| `manifest.json` | Version, when it was built, and the cube structure it was built from |

## `cubes/<cube>.json`

```json
{
  "cube": "GlobalTravelEngine - Bookings",
  "label": "Bookings",
  "purpose": "Sales, cost, profit and counts of booking lines. Two sentences at most.",
  "grain": "One booking line (reservation service).",
  "use_for": ["sales, cost and profit", "number of bookings"],
  "not_for": ["payments collected (Booking Payments)", "search volumes (Statistics Zone)"],
  "coverage": {"main_date": "'Calendar'[Date]", "first": "2014-10", "last": "2026-10", "note": ""},
  "dates": [
    {"column": "'Calendar'[Date]", "role": "booking_date", "label": "Booking date",
     "meaning": "When the booking was made (the cube's main date).", "default": true,
     "words": ["booked", "booking date", "made"], "first": "2014-10", "last": "2026-10"}
  ],
  "measures": [
    {"name": "[Reservations Count]", "label": "Bookings", "definition": "Number of booking lines.",
     "unit": "count", "format": ",.0f", "prefix": "", "aggregation": "sum",
     "terms": ["bookings", "number of bookings", "reservations"],
     "default_date_role": "booking_date", "date_roles": ["booking_date", "creation_date"],
     "status": "active", "hidden_reason": "", "confidence": "high", "notes": ""}
  ],
  "breakdowns": [
    {"column": "'Sale Channel'[Sale Channel]", "label": "Sale channel", "entity": "sale_channel",
     "kind": "enum", "meaning": "B2B, B2C or XML.", "needs_columns": ["'Sale Channel'[Sale Channel.UniqueName]"],
     "sort_by": "", "distinct": 4, "sample_values": ["XML - GTE - Global Travel Engine"], "status": "active"}
  ],
  "named_filters": [
    {"name": "cancelled bookings", "meaning": "Bookings cancelled by the client or the system.",
     "column": "'Booking Status'[Status Name]", "values": ["Client Cancelled Bookings", "Cancelled"],
     "confidence": "medium"}
  ],
  "rules": ["Use the cube's measures only; never SUM a column."],
  "examples": [
    {"question": "Bookings by sale channel last month", "measures": ["[Reservations Count]"],
     "breakdowns": ["'Sale Channel'[Sale Channel]"], "date_role": "booking_date"}
  ],
  "review": [
    {"id": "bookings.sales_term", "question": "Does \"sales\" mean Sale (with tax) or Final Sales?",
     "options": ["[Sale]", "[Final Sales]"], "proposed": "[Sale]", "why": "..."}
  ]
}
```

### Field rules

- **dates** — only the day-level date columns a period can filter on (`Date/time` columns). Exactly one has
  `"default": true`: the date a plain question ("bookings in September") means. `role` comes from the
  shared vocabulary below so the same word means the same thing in every cube. `words` are phrases that
  select this date ("travel", "stay", "check-in").
- **measures** — every measure of the cube appears once.
  - `status: "hidden"` for helpers the app must not use: last-year / variance / growth / optimisation
    variants (`LY`, `LYS`, `Var`, `Growth`, `Opt`), duplicates of another measure, measures with no data at
    all, and purely technical ones. Say why in `hidden_reason` (e.g. `"last-year helper of [Sale]"`,
    `"no data"`). The app makes period comparisons itself, so LY helpers are never needed.
  - `unit`: `count`, `currency:AED` (or the right currency), `percent` (stored as a fraction 0–1),
    `percent_0_100`, `ratio`, `seconds`, `milliseconds`, `bytes`, `kilobytes`, `megabytes`, `gigabytes`,
    `nights`, `people`, `days`, `hours`.
  - `format` is a d3 format (`,.0f`, `~s`, `.1%`, `,.2f`) and `prefix`/`suffix` the unit around it.
  - `aggregation`: `sum` (adds up across any breakdown), `average`, `ratio`, `distinct_count`, `max`, `min`,
    `last`. Only `sum` measures may be added across rows or cubes.
  - `terms`: the business words this measure answers *in this cube*, lower case. The one measure that
    answers a term across all cubes is chosen in `terms.json`.
  - `confidence`: `high` when the name, format and data leave no doubt; `medium` when it is the most likely
    reading; `low` otherwise (then add a review item).
- **breakdowns** — the attributes people group or filter by. `needs_columns` are the helper columns the
  cube requires next to it in any query (from the structure file's "group with"). `kind`: `enum` (a short
  fixed list: statuses, channels, markets, product types), `name` (customers, hotels, suppliers...),
  `code`, `date_part` (year, month, week). Hide technical attributes (keys, ISO sort columns, IDs nobody
  asks for).
- **sample_values** — only for `enum` breakdowns, at most 8. **Never** customer, hotel, supplier, agency
  or person names, booking numbers or e-mail addresses: this file is public.
- **named_filters** — business definitions used in questions ("confirmed bookings", "owned hotels",
  "UAE market"), as a column and its exact stored values.
- **review** — only decisions a business person must make (which of two plausible measures a common
  word means, which date a plain question means when it is not obvious). Give a proposed answer.

### Shared date-role vocabulary

`booking_date` (booking made/main booking date) · `creation_date` (record created in the system) ·
`travel_date` (service/travel start, check-in) · `stay_date` (each night of a stay) ·
`occupancy_date` (allotment night) · `payment_date` · `cancellation_date` · `request_date`
(API request or search) · `lock_date` · `modification_date` · `invoice_date` · `due_date` ·
`last_year_date` (LY helper dates: always hidden from questions). Use another snake_case name only if
none fits, and explain it in `meaning`.
