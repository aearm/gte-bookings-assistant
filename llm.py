"""Claude turns questions into query plans (one query per cube, joined when a question needs
several cubes), and results into a chart + short answer. What Claude knows about the data comes
from the data layer (data_layer.py)."""
import json
import re
import time

import anthropic
import pandas as pd

import charts
import config
import dynamic_chart
import usage

_client = None
_client_key = ""
_fallbacks_ok = True  # server-side refusal fallback; switched off if the account doesn't accept it
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5")


def _get_client() -> anthropic.Anthropic:
    global _client, _client_key
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("No Claude API key is set. Add it on the Settings page.")
    if _client is None or _client_key != config.ANTHROPIC_API_KEY:  # key changed on Settings page
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        _client_key = config.ANTHROPIC_API_KEY
    return _client


def check_connection() -> None:
    """Raises if the API key or model doesn't work. Uses no tokens."""
    _get_client().models.retrieve(config.CLAUDE_MODEL)


def _create(purpose: str = "", **kwargs):
    """One request (streamed, so long answers don't time out), recorded in usage (tokens, cache,
    seconds, cost) under its purpose. If the model declines on safety grounds, the API re-runs the
    request on Anthropic's recommended fallback model."""
    started = time.perf_counter()
    response = _send(**kwargs)
    usage.record_call(purpose, getattr(response, "model", "") or kwargs["model"], getattr(response, "usage", None),
                      time.perf_counter() - started)
    return response


def _send(**kwargs):
    global _fallbacks_ok
    client = _get_client()
    if _fallbacks_ok and kwargs["model"] in FALLBACK_MODELS:
        try:
            with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                             **kwargs) as stream:
                return stream.get_final_message()
        except anthropic.BadRequestError as exc:
            if "fallback" not in str(exc).lower() and "beta" not in str(exc).lower():
                raise
            _fallbacks_ok = False  # not available for this account: plain requests from now on
    with client.messages.stream(**kwargs) as stream:
        return stream.get_final_message()


# ---------------------------------------------------------------- rules --

DAX_RULES = """Rules for DAX queries (Analysis Services cubes):
- The query must start with EVALUATE (or DEFINE ... EVALUATE). It is read-only.
- Use only the exact table, column and measure names of the cube it runs on (see its details).
  Write columns as 'Table'[Column] and measures as [Measure Name].
- If a column has "group with" columns, list those hidden columns right next to it every time you
  group by or filter that column (SUMMARIZECOLUMNS, SUMMARIZE, ALL), e.g.
  SUMMARIZECOLUMNS('Countries'[Country.UniqueName], 'Countries'[Country], "Bookings", [Bookings]).
  Filter such a column with KEEPFILTERS(FILTER(ALL('Countries'[Country], 'Countries'[Country.UniqueName]),
  'Countries'[Country] = "Spain")), never with TREATAS or 'Countries'[Country] = "Spain" as a CALCULATE
  filter. Otherwise the server rejects the query. They are removed from the result automatically.
  To put such a column in its natural order, also group by its "sort by" column and ORDER BY it.
- Prefer existing measures. Typical shape:
    EVALUATE
    SUMMARIZECOLUMNS('Date'[Year], 'Destination'[Country], "Bookings", [Total Bookings])
    ORDER BY 'Date'[Year]
- Give each measure a short readable label in SUMMARIZECOLUMNS ("Bookings", "Revenue").
- Show people names, not only codes: when a breakdown (customer, supplier, hotel, agency...) has a name
  column, group by it too, so the result reads "Desert Pearl Tours", not "1042". Keep the code as well
  when it is needed to join cubes or to tell apart members with the same name.
- Filters go inside SUMMARIZECOLUMNS, e.g. KEEPFILTERS(FILTER(ALL('Date'[Year]), 'Date'[Year] >= 2025)),
  with the column's group-with columns inside ALL() when it has them (TREATAS only for a column without).
- For "top N" questions wrap with TOPN(N, <table>, [Label], DESC) and ORDER BY the label.
- Always add ORDER BY (dates ascending, rankings descending).
- Keep results small (well under MAX_ROWS rows): pick a sensible grain, e.g. months not days
  for long periods. Never return raw transaction-level rows unless asked.
- When a breakdown has many values (hotels, customers, destinations, suppliers...) and the question
  doesn't ask for all of them, return the top 25 by the main number with TOPN, and say so in the
  understanding (e.g. "top 25 hotels by sales")."""

SQL_RULES = """Rules for SQL queries (DuckDB dialect, local data files):
- One read-only SELECT statement (WITH ... SELECT is fine). No other statements.
- Use only the exact table and column names listed in the schema. Tables can be joined in the query.
  Always wrap column names in double quotes, e.g. "Booking Date", "Sales USD".
- Aggregate with GROUP BY and give result columns short readable aliases ("Bookings", "Revenue").
- Show names, not only codes: when a breakdown has a name column, return it (keep the code too when it is
  needed to join or to tell members apart).
- Months: strftime(date_trunc('month', "Some Date"), '%Y-%m') AS "Month". Years: year("Some Date").
- Round money to 2 decimals. For "top N" use ORDER BY ... DESC LIMIT N.
- Always add ORDER BY (dates ascending, rankings descending).
- Keep results small (well under MAX_ROWS rows): pick a sensible grain, e.g. months not days
  for long periods. Never return raw row-level data unless asked.
- When a breakdown has many values and the question doesn't ask for all of them, return the top 25
  by the main number (ORDER BY ... DESC LIMIT 25), and say so in the understanding.
- Dates: use DATE 'YYYY-MM-DD' literals, not current_date.
- Use the listed example values to match filters exactly (e.g. country or status spellings)."""

PLAN_RULES = """You answer business questions about a travel company's data. The index cards below
describe every cube in a few lines (what it is for, its main measures, dates and dimensions) and which
cubes share dimensions. With the question you get the full details of the cubes most likely needed,
the join path between them, and the values of the question already found in the data. Today's date is
TODAY_DATE; use it for "this year", "last month" and so on.

How to answer:
1. Use the cube(s) given in full with the question when they hold the numbers asked for. Prefer ONE
   cube; use several only when the numbers asked for live in different cubes.
2. Write queries only against cubes whose full details you have. If another cube fits better, read its
   details first with get_cube_details.
3. Write the plan:
   - steps: one query per cube: name (short, lowercase letters and _, used as a table name in
     combine_sql), cube (exact cube name from the data layer), query.
   - combine_sql: empty when there is one step. With several steps: ONE DuckDB SELECT that joins the
     steps' results, using each step's name as a table name.

Joining cubes (several steps):
- Aggregate each step to exactly the grain of the final answer (the same breakdown), so the join is
  one row to one row. Never return transaction-level rows to join them.
- Join only on the shared dimensions listed in the data layer, on the join columns given there for each
  cube. Compare text keys with upper(trim(...)). Never join on measures.
- Join dates at the same grain in every step (e.g. each step groups by its own year and month number
  columns), on the date each cube's question means (bookings by booking date, payments by payment date...).
- Use FULL OUTER JOIN and COALESCE the keys when comparing numbers from different cubes, so members
  found in one cube only are kept; use an INNER JOIN only when the question asks for members in both.
- Never add up averages or percentages; compute ratios in combine_sql from summable numbers, e.g.
  SUM(p."Payments") / NULLIF(SUM(b."Sales"), 0).
- In combine_sql, quote column names in double quotes. A step's result columns are named like this:
  a grouped column by its column name without the table ('Customers'[Code] -> "Code"; when two have
  the same name: "Customers Code"), a measure by the label you gave it. Give the final columns clear
  names ("Customer", "Sales", "Payments") and an ORDER BY. When steps are joined on a code, carry the
  name through (from the step that has it), so the result shows who each row is.

LANGUAGE_RULES

Answering:
- "understanding": restate the question in one plain sentence a business user can check: the number
  (which measure, from which cube), how it is broken down, the exact period with dates (e.g. 1-30 Sep
  2026) and which date it is based on, any filters, top-N or sorting, and how cubes are combined.
- If a sensible reading exists, set needs_clarification to false and write the plan. Where you had
  to pick a default (period, date, which measure or cube), say so in the understanding.
- Set needs_clarification to true only when you cannot pick a sensible reading: the question names
  nothing you can measure, or it could mean very different things that would give very different
  numbers, and neither the glossary, the business notes nor earlier questions settle it. Then leave
  steps empty, ask ONE short question in clarifying_question and give 2-4 short answer options.
- "chart_request": copy any instructions the user gave about how to show the result (chart type,
  axes, series, colours, sorting, labels, "as a table"...), else empty.
- "reuse_previous": true only when the new message only asks to show the previous answer
  differently (another chart, order, colours) and needs no new data; then leave steps empty.
- If earlier questions are given, treat the new question as a follow-up to them."""

CHECK_RULES = """Check the data with your tools only where needed (at most MAX_ROUNDS rounds of checks):
- Values of the question already found in the data are listed with it: use them, don't look them up
  again. For any other word or name that refers to a value (a status, market, country, channel,
  customer, supplier, product...), call find_values to see which cubes and columns contain it, the
  exact value and how much data it has. Look up several words in the same turn.
- If a phrase matches values in more than one column with different meanings (e.g. a market and a
  country), or matches only a value with no data, ask: set needs_clarification and give the real values
  as options, e.g. "Market = UAE". Don't ask if an Agreed glossary entry or the business notes settle
  it; a Draft glossary entry does not settle which values to filter on.
- If you are unsure a query returns data (or which columns it returns, before joining it), check it
  with preview_query.
- Filter only on exact values you found."""

_STEP = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short lowercase name, e.g. bookings."},
        "cube": {"type": "string", "description": "Exact cube name from the data layer."},
        "query": {"type": "string", "description": "The complete query for that cube."},
    },
    "required": ["name", "cube", "query"],
    "additionalProperties": False,
}
PLAN_TOOL = {
    "name": "submit_plan",
    "description": "Submit the plan that answers the user's question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "understanding": {"type": "string"},
            "needs_clarification": {"type": "boolean"},
            "clarifying_question": {"type": "string", "description": "Only when needs_clarification is true, else empty."},
            "options": {"type": "array", "items": {"type": "string"}, "description": "2-4 short answers, else empty."},
            "reuse_previous": {"type": "boolean"},
            "steps": {"type": "array", "items": _STEP, "description": "One query per cube used; empty when asking."},
            "combine_sql": {"type": "string", "description": "DuckDB SELECT joining the steps, or empty for one step."},
            "explanation": {"type": "string", "description": "One plain sentence: what the plan returns and any assumption made."},
            "chart_request": {"type": "string", "description": "The user's own instructions for the chart, or empty."},
        },
        "required": ["understanding", "needs_clarification", "clarifying_question", "options", "reuse_previous",
                     "steps", "combine_sql", "explanation", "chart_request"],
    },
}

_FORMAT = {
    "type": "object",
    "properties": {
        "column": {"type": "string", "description": "Exact number column."},
        "d3_format": {"type": "string", "description": "d3 number format for its axis, hover and labels: ',.0f' "
                      "whole numbers, ',.2f' averages, '.1%' fractions shown as percent, '~s' compact (4.5M)."},
        "prefix": {"type": "string", "description": "e.g. 'AED ' for money, else empty."},
        "suffix": {"type": "string", "description": "e.g. '%' when values are already 0-100, ' nights', ' s', else empty."},
    },
    "required": ["column", "d3_format", "prefix", "suffix"],
    "additionalProperties": False,
}
STYLE = {
    "type": "object",
    "description": "How the chart is formatted; the app draws it exactly like this.",
    "properties": {
        "formats": {"type": "array", "items": _FORMAT, "description": "One per number column shown."},
        "x_title": {"type": "string", "description": "Title of the axis with the categories or dates, or empty."},
        "y_title": {"type": "string", "description": "Title of the axis with the numbers, with the unit, or empty."},
        "sort": {"type": "string", "enum": ["value_desc", "value_asc", "label", "none"]},
        "show_values": {"type": "boolean", "description": "Write each value on its bar or slice."},
        "label_angle": {"type": "integer", "enum": [0, -30, -45, -90]},
        "legend": {"type": "string", "enum": ["top", "right", "bottom", "none"]},
        "log_scale": {"type": "boolean"},
        "measures": {"type": "string", "enum": ["auto", "one_chart", "panels"],
                     "description": "How several measures of different size or unit are drawn: auto (one panel "
                                    "each), one_chart (all in one chart, each measure on its own axis, bars side by "
                                    "side - when the user asks for them in one chart), panels."},
    },
    "required": ["formats", "x_title", "y_title", "sort", "show_values", "label_angle", "legend", "log_scale",
                 "measures"],
    "additionalProperties": False,
}

CHART_TOOL = {
    "name": "submit_chart",
    "description": "Choose how to display the result and answer the question in words.",
    "input_schema": {
        "type": "object",
        "properties": {
            "chart_type": {"type": "string", "enum": charts.CHART_TYPES + ["custom"],
                           "description": (
                               "Pick the chart that answers the question best: map when the breakdown is by "
                               "country; line (or area) for trends over time; donut for 2-6 parts of a whole; "
                               "treemap for shares across many parts; horizontal_bar for rankings / top N or long "
                               "names; bar to compare a few categories; stacked_bar for a category split by a "
                               "second one with few values; heatmap for two breakdowns with many values (e.g. "
                               "market by month); scatter to relate two numbers; table when a chart would not "
                               "help (e.g. a single row with many numbers); custom only for a chart the user "
                               "described that no other type draws exactly. Several measures of very different "
                               "size or unit are drawn automatically as one panel each, with their own scales.")},
            "x": {"type": "string", "description": "Column for the x-axis, the labels, or the countries (map). Exact column name."},
            "y": {"type": "array", "items": {"type": "string"}, "description": "Numeric column(s) to plot. Exact column names."},
            "color": {"type": "string", "description": "Second breakdown column (series of a line / bars side by side / stacked bar, rows of a heatmap), e.g. the day or channel, or empty."},
            "custom_chart": {"type": "string", "description": "Only for chart_type custom: the chart spec as JSON, else empty."},
            "style": STYLE,
            "title": {"type": "string"},
            "summary": {"type": "string", "description": "2-3 sentences answering the question with the key numbers, "
                        "formatted like the chart (e.g. AED 4.5M, 12.3%). Plain English."},
        },
        "required": ["chart_type", "title", "summary", "style"],
    },
}

FORMAT_RULES = """Format the chart so it reads best for this data and question; it is drawn exactly as you say.
- formats: one per number column on the chart, from what the number is (see the query and the measures):
  money gets the currency as prefix ("AED ") with ',.0f', or '~s' once values reach the hundreds of
  thousands (AED 4.5M); counts ',.0f' (or '~s' when in the millions); fractions (0.123) '.1%'; numbers
  already 0-100 that are percentages ',.1f' with suffix '%'; averages and ratios ',.2f'; durations with
  their unit as suffix.
- title: what is shown, with the period if known, e.g. "Sales by month, 2026". y_title: the measure and
  unit, e.g. "Sales (AED)"; empty when there are several measures (the legend names them) or for donut,
  treemap and map. x_title: empty when obvious (months, countries), else short.
- sort: value_desc for rankings and categories so the biggest comes first; label for dates, weeks,
  months and natural orders (age bands, star ratings); none to keep the query's order.
- show_values: true for up to about 12 bars or 7 slices, so the exact numbers are on the chart; false for
  lines, maps and dense charts.
- label_angle: 0 for short labels; -45 when there are many or long category labels on the x axis
  (use horizontal_bar instead when names are long).
- legend: none for a single series; top otherwise.
- log_scale: only when values span several orders of magnitude and the point is to compare many items.
- Several measures: put every measure the question asks for in y - never drop one. When they differ a lot
  in size or unit (requests in millions, bookings in tens, sales in AED) they are drawn as one panel per
  measure, each with its own scale and format, sharing the categories; with a second breakdown in color
  (e.g. the day), each panel shows one bar per value side by side ("3 bars for each day" = y with the 3
  measures, color the day). Use bar or horizontal_bar for categories, line for time.
- measures: one_chart when the user wants them together in one chart (e.g. "6 bars for each customer, 3
  per day", "all in one chart"): each measure gets its own axis (up to 3, coloured like its bars) and the
  bars stand side by side, the second breakdown in shades of each measure's colour. Otherwise auto.
- For chart_type custom, put the same formatting in the Plotly spec (tickformat, tickprefix, hovertemplate,
  texttemplate, axis titles, categoryorder) and still fill style."""

DYNAMIC_RULES = """The user described the chart they want: follow their description exactly.
If a standard chart_type draws exactly what they asked, use it. Otherwise set chart_type to "custom"
and write custom_chart: a JSON object {"prepare": {...}, "traces": [...], "layout": {...}}.
- traces are Plotly traces: bar, scatter (lines and/or markers; fill "tozeroy" for areas), pie, funnel,
  funnelarea, waterfall, indicator, treemap, sunburst, icicle, heatmap, histogram, box, violin,
  scatterpolar, barpolar, choropleth, scattergeo, sankey, table... Wherever a trace takes data, write
  {"col": "<exact result column>"}, e.g. "x": {"col": "Month"}, "y": {"col": "Sales"}.
- "split_by": "<column>" in a trace draws one series per value of that column (e.g. a line per channel).
- treemap / sunburst / icicle: "path": ["<outer column>", "<inner column>"] and "values": {"col": "<number>"}.
- "prepare" is optional: {"group_by": [...], "aggregate": {"<column>": "sum|mean|min|max|count|median"},
  "sort_by": "<column>", "descending": true, "top": 10}.
- layout is a Plotly layout, e.g. "barmode": "stack" | "group" | "relative", "barnorm": "percent",
  a second axis ("yaxis2": {"overlaying": "y", "side": "right", "title": {"text": "..."}} with
  "yaxis": "y2" on the trace), axis titles, "tickformat": ",.0f" or ".0%", "xaxis": {"type": "category"}.
  Horizontal bars: "orientation": "h" on the trace, with x and y swapped.
  Don't set fonts or backgrounds; set colours only if the user asked for them.
- Use only columns of the result. If the user asks for a number the result doesn't have, draw what
  you can and say so in the summary."""


# ---------------------------------------------------------------- calls --

MAX_CHECK_ROUNDS = 6  # rounds of data checks (tool calls) before Claude must answer


def _structured_call(system: list, tool: dict, user_text: str | list, tools: list | None = None,
                     run_tool=None, on_step=None, model: str | None = None, effort: str | None = None,
                     max_tokens: int = 16000, purpose: str = "") -> dict:
    """Ask Claude for JSON matching the tool's schema (structured outputs). With tools, Claude may
    first call them (e.g. to look up values); run_tool(name, input) answers each call."""
    schema = {**tool["input_schema"], "additionalProperties": False}
    messages = [{"role": "user", "content": user_text}]
    output_config = {"format": {"type": "json_schema", "schema": schema}}
    if effort:
        output_config["effort"] = effort
    for check_round in range(MAX_CHECK_ROUNDS + 1):
        extra = {}
        if tools and run_tool:
            extra["tools"] = tools
            # the whole conversation so far is re-read from the cache in the next round of checks (a single
            # call has no next round: caching its unique tail would only add the 25% write premium)
            extra["cache_control"] = {"type": "ephemeral"}
            if check_round == MAX_CHECK_ROUNDS:
                extra["tool_choice"] = {"type": "none"}  # enough checking: answer now
        response = _create(
            purpose=purpose,
            model=model or config.CLAUDE_MODEL,
            max_tokens=max_tokens,  # Claude thinks before answering, and thinking counts toward this limit
            system=system,
            output_config=output_config,
            messages=messages,
            **extra,
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined to answer this question. Try rephrasing it.")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Claude's answer was cut off. Try a simpler or narrower question.")
        calls = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason == "tool_use" and calls:
            messages.append({"role": "assistant", "content": response.content})  # keep thinking blocks
            results = []
            for call in calls:
                if on_step:
                    on_step(call.name, call.input)
                try:
                    results.append({"type": "tool_result", "tool_use_id": call.id,
                                    "content": run_tool(call.name, call.input)})
                except Exception as exc:
                    results.append({"type": "tool_result", "tool_use_id": call.id, "is_error": True,
                                    "content": f"The check failed: {str(exc).splitlines()[0][:300]}"})
            messages.append({"role": "user", "content": results})
            continue
        for block in response.content:
            if block.type == "text":
                return json.loads(block.text)
        raise RuntimeError("Claude did not return a result. Try rephrasing the question.")
    raise RuntimeError("Claude did not finish checking the data. Try a simpler question.")


def plan_rules(language: str, today: str) -> str:
    rules = PLAN_RULES.replace("LANGUAGE_RULES", DAX_RULES if language == "DAX" else SQL_RULES)
    return rules.replace("MAX_ROWS", str(config.MAX_ROWS)).replace("TODAY_DATE", today)


def question_to_plan(question: str, cards: str, details: list[tuple[str, str]], today: str,
                     language: str = "DAX", context: list[dict] | None = None, failed_plan: str | None = None,
                     error: str | None = None, clarification: tuple[str, str] | None = None,
                     instructions: str = "", hits: str = "", join: str = "", examples: list[dict] | None = None,
                     tools: list | None = None, run_tool=None, on_step=None, periods: str = "") -> dict:
    """The plan for a question: one query per cube (+ the SQL joining them).
    cards = every cube's index card (always the same, so it stays cached); details = [(cube, full
    details)] of the cubes picked for this question; hits = values of the question found in the data;
    join = how the picked cubes join; examples = verified answers to similar questions; periods = the
    question's periods with their exact dates, worked out by code (rewrite.py).
    clarification = (question Claude asked, the user's answer). instructions = extra requirements,
    e.g. for a dashboard chart. tools + run_tool let Claude check the data (on_step(name, input)
    reports each check). A result with needs_clarification or reuse_previous has no steps."""
    # The rules and cards are the same for every question, and a cube's details for every question about
    # it: both cached for an hour (the next questions read them for a twentieth of the price). The cubes
    # always come in the same order, so a question about the same cubes finds them in the cache.
    checking = "\n\n" + CHECK_RULES.replace("MAX_ROUNDS", str(MAX_CHECK_ROUNDS)) if tools and run_tool else ""
    system = [{"type": "text", "text": plan_rules(language, today) + checking + "\n\n" + cards,
               "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    details = sorted(details)
    blocks = []
    for i, (cube, text) in enumerate(details):
        block = {"type": "text", "text": f"# Full details of the cube \"{cube}\"\n{text}"}
        if i < 2:  # at most 4 cache points per request: system, two cubes, and the conversation
            block["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
        blocks.append(block)

    parts = []
    if details:
        parts.append("Cubes picked for this question (full details above): "
                     + ", ".join(f'"{c}"' for c, _ in details))
    if join:
        parts.append("How these cubes join:\n" + join)
    if hits:
        parts.append("Values of the question found in the data (cube, column = exact value (amount of data)):\n" + hits)
    if periods:
        parts.append("Periods of the question, worked out by code from today's date (filter exactly these first and "
                     "last days, on the date each number is counted on):\n" + periods)
    for ex in examples or []:
        parts.append(f"A similar question answered correctly before (adapt it, including the dates, to today):\n"
                     f"Question: {ex['question']}\nUnderstood as: {ex['understanding']}\nPlan:\n"
                     + json.dumps(ex["plan"], ensure_ascii=False)[:3000])
    for prev in (context or [])[-3:]:
        parts.append(f"Earlier question: {prev['question']}\nEarlier plan:\n{prev['query']}")
    parts.append(f"Question: {question}")
    if clarification:
        parts.append(f"You asked: {clarification[0]}\nThe user answered: {clarification[1]}\n"
                     "Use this answer. Only ask again about something different that is still unclear.")
    if instructions:
        parts.append(instructions)
    if failed_plan:
        parts.append(f"Your previous plan failed.\nPlan:\n{failed_plan}\n\nError:\n{error}\n\n"
                     "Fix it (check names against the cube details, and the steps' column names). "
                     "Do not ask for clarification.")
    content = lambda: blocks + [{"type": "text", "text": "\n\n".join(parts)}]
    result = _structured_call(system, PLAN_TOOL, content(), tools, run_tool, on_step,
                              effort=config.CLAUDE_PLAN_EFFORT, purpose="plan")
    if result.get("needs_clarification") and result.get("clarifying_question") and not failed_plan:
        result["steps"] = []
        return result
    if result.get("reuse_previous") and context and not failed_plan and not instructions:
        result["steps"] = []
        return result
    if not [s for s in result.get("steps", []) if s.get("query", "").strip()]:
        parts.append("You did not return any query. Using what you found, write the plan now "
                     "(needs_clarification false, reuse_previous false).")
        # the same tools as the first call: different tools would make the whole cached prompt a miss
        result = _structured_call(system, PLAN_TOOL, content(), tools, run_tool, on_step,
                                  effort=config.CLAUDE_PLAN_EFFORT, purpose="plan")
    result["needs_clarification"] = False
    result["reuse_previous"] = False
    if language == "DAX":
        for step in result.get("steps", []):
            validate_dax(step.get("query", ""))
    if not result.get("steps"):
        raise RuntimeError("Claude did not return a query. Try rephrasing the question.")
    return result


def dashboard_instructions(language: str, date_column: str, kpi: bool, base_query: str = "") -> str:
    """Extra requirements for a dashboard chart: the dashboard, not the question, sets the period.
    date_column "auto" = each step filters on its cube's main date."""
    lines = ["This plan is for a dashboard chart that is re-run for whatever period the user picks."]
    if base_query:
        lines.append("Start from this plan, which answered the question in a chat. Keep its cubes, measures, "
                     f"breakdown, joins, sorting and top-N, but change the period as described below:\n{base_query}")
    if date_column == "auto":
        filt = ("KEEPFILTERS(FILTER(ALL(<date column>), <date column> >= @START && <date column> < @END)) inside "
                "SUMMARIZECOLUMNS" if language == "DAX" else "<date column> >= @START AND <date column> < @END")
        lines.append(f"In every step, filter the period on the date the question means in that cube (by default the "
                     f"cube's default date in the data layer) with exactly {filt}.")
    elif date_column and language == "DAX":
        lines.append(f"Filter the period on {date_column} with exactly KEEPFILTERS(FILTER(ALL({date_column}), "
                     f"{date_column} >= @START && {date_column} < @END)) inside SUMMARIZECOLUMNS. ")
    elif date_column:
        lines.append(f"Filter the period with {date_column} >= @START AND {date_column} < @END.")
    if date_column:
        lines.append("Write @START and @END literally: they are replaced with dates when the chart runs. "
                     "Remove any other period or date filter, including one in the question.")
    else:
        lines.append("Do not filter by date: the chart covers all dates. Remove any period in the question.")
    if kpi:
        lines.append("Return exactly one row with one number (the headline figure), no other columns.")
    lines.append("Set needs_clarification and reuse_previous to false.")
    return "\n".join(lines)


def validate_dax(dax: str) -> None:
    if not dax.strip():
        raise RuntimeError("Claude did not return a query. Try rephrasing the question.")
    body = re.sub(r"(--|//).*?$", "", dax, flags=re.MULTILINE)  # drop comment lines
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL).strip()
    if not re.match(r"^(DEFINE|EVALUATE)\b", body, flags=re.IGNORECASE):
        raise ValueError("Generated query does not start with EVALUATE/DEFINE, so it was not run.")


def data_profile(df: pd.DataFrame) -> str:
    """What each column holds: ranges of numbers, sizes of labels (for choosing formats)."""
    lines = []
    for c in df.columns:
        col = df[c]
        if pd.api.types.is_numeric_dtype(col) and col.notna().any():
            lines.append(f"- {c}: number, min {col.min():,.6g}, median {col.median():,.6g}, max {col.max():,.6g}")
        else:
            values = col.dropna().astype(str)
            examples = ", ".join(values.unique()[:4])
            lines.append(f"- {c}: text/date, {values.nunique():,} different, up to {values.str.len().max() or 0} "
                         f"characters, e.g. {examples}")
    return "\n".join(lines)


def describe_result(question: str, df: pd.DataFrame, chart_request: str = "", query: str = "",
                    measures: str = "") -> dict:
    """The chart, formatted for this data, and the written answer. chart_request = the user's own
    description of the chart they want; Claude may then draw any chart (a 'custom' spec, see
    dynamic_chart.py). query and measures (what the numbers are, from the data layer) help Claude
    pick formats: currency, percent, counts."""
    sample = df.head(60).to_csv(index=False)
    rules = ("You present query results for business users. Pick the clearest chart, format it for the data, "
             "and answer the question in plain English using the numbers shown. Do not invent numbers.\n\n"
             + FORMAT_RULES)
    if chart_request:
        rules += "\n\n" + DYNAMIC_RULES
    system = [{"type": "text", "text": rules, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]  # same every time
    hint = charts.suggest(df)
    user = (f"Question: {question}\n\nResult has {len(df)} rows. Columns:\n{data_profile(df)}\n"
            + (f"\nThe query that produced it:\n{query[:2500]}\n" if query else "")
            + (f"\nWhat the numbers are:\n{measures}\n" if measures else "")
            + (f"\nThe user asked for this chart: {chart_request}\n" if chart_request else
               f"\nFrom the shape of the data the best fit looks like: {hint['chart_type']} "
               f"(x={hint['x']!r}, color={hint['color']!r}). Use it unless another chart answers the question better.\n")
            + f"\nFirst rows (CSV):\n{sample}")
    model, effort = (config.CLAUDE_MODEL, "low") if chart_request else (config.CLAUDE_FAST_MODEL, "low")
    spec = _structured_call(system, CHART_TOOL, user, model=model, effort=effort, purpose="chart")
    spec.setdefault("y", [])
    if spec.get("chart_type") == "custom":
        problem = _custom_problem(df, spec)
        if problem:  # one more try, with what went wrong
            spec = _structured_call(system, CHART_TOOL, user + f"\n\nYour custom_chart could not be drawn: {problem}\n"
                                    "Fix it.", model=model, effort=effort, purpose="chart")
            spec.setdefault("y", [])
            problem = _custom_problem(df, spec) if spec.get("chart_type") == "custom" else ""
        if problem:
            spec = {**charts.suggest(df), "title": spec.get("title", ""), "summary": spec.get("summary", ""),
                    "style": spec.get("style", {}),
                    "note": "The chart you described couldn't be drawn from this data, so the best standard chart is shown."}
        elif spec.get("chart_type") == "custom":
            spec["custom"] = dynamic_chart.parse(spec.pop("custom_chart"))
            spec["chart_request"] = chart_request
            return spec
    spec.pop("custom_chart", None)
    return charts.fit(df, spec)


def _custom_problem(df: pd.DataFrame, spec: dict) -> str:
    if not spec.get("custom_chart"):
        return "custom_chart is empty."
    return dynamic_chart.check(df, spec["custom_chart"])
