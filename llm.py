"""Claude turns questions into DAX, and results into a chart + short answer."""
import json
import re

import anthropic
import pandas as pd

import charts
import config

_client = None
_client_key = ""


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


DAX_RULES = """You write DAX queries for a SQL Server Analysis Services model of travel bookings.
The user asks a question in plain English; you answer with ONE DAX query and a short explanation.

Rules:
- The query must start with EVALUATE (or DEFINE ... EVALUATE). It is read-only.
- Use only the exact table, column and measure names listed in the schema below.
  Write columns as 'Table'[Column] and measures as [Measure Name].
- If the schema says a column has "group with" columns, list those hidden columns right next to it
  every time you group by that column (SUMMARIZECOLUMNS, SUMMARIZE, VALUES), e.g.
  SUMMARIZECOLUMNS('Countries'[Country.UniqueName], 'Countries'[Country], "Bookings", [Bookings]).
  Otherwise the server rejects the query. They are removed from the result automatically.
  To put such a column in its natural order, also group by its "sort by" column and ORDER BY it.
- Prefer existing measures. Typical shape:
    EVALUATE
    SUMMARIZECOLUMNS('Date'[Year], 'Destination'[Country], "Bookings", [Total Bookings])
    ORDER BY 'Date'[Year]
- Give each measure a short readable label in SUMMARIZECOLUMNS ("Bookings", "Revenue").
- Filters go inside SUMMARIZECOLUMNS, e.g. TREATAS({"Spain"}, 'Destination'[Country])
  or KEEPFILTERS(FILTER(ALL('Date'[Year]), 'Date'[Year] >= 2025)).
- For "top N" questions wrap with TOPN(N, <table>, [Label], DESC) and ORDER BY the label.
- Always add ORDER BY (dates ascending, rankings descending).
- Keep results small (well under MAX_ROWS rows): pick a sensible grain, e.g. months not days
  for long periods. Never return raw transaction-level rows unless asked.
- When a breakdown has many values (hotels, customers, destinations, suppliers...) and the question
  doesn't ask for all of them, return the top 25 by the main number with TOPN, and say so in the
  understanding (e.g. "top 25 hotels by sales").
- "This year", "last month" etc.: today's date is TODAY_DATE.
- If an earlier question is given as context, treat the new question as a follow-up to it.
"""

SQL_RULES = """You write SQL queries (DuckDB dialect) over tables of travel bookings data.
The user asks a question in plain English; you answer with ONE SQL query and a short explanation.

Rules:
- One read-only SELECT statement (WITH ... SELECT is fine). No other statements.
- Use only the exact table and column names listed in the schema below.
  Always wrap column names in double quotes, e.g. "Booking Date", "Sales USD".
- Aggregate with GROUP BY and give result columns short readable aliases ("Bookings", "Revenue").
- Months: strftime(date_trunc('month', "Some Date"), '%Y-%m') AS "Month". Years: year("Some Date").
- Round money to 2 decimals. For "top N" use ORDER BY ... DESC LIMIT N.
- Always add ORDER BY (dates ascending, rankings descending).
- Keep results small (well under MAX_ROWS rows): pick a sensible grain, e.g. months not days
  for long periods. Never return raw row-level data unless asked.
- When a breakdown has many values (hotels, customers, destinations, suppliers...) and the question
  doesn't ask for all of them, return the top 25 by the main number (ORDER BY ... DESC LIMIT 25),
  and say so in the understanding.
- "This year", "last month" etc.: today's date is TODAY_DATE (use DATE 'TODAY_DATE', not current_date).
- Use the listed example values to match filters exactly (e.g. country or status spellings).
- If an earlier question is given as context, treat the new question as a follow-up to it.
"""

ANSWER_RULES = """
How to answer:
- "understanding": restate the question in one plain sentence a business user can check: the number
  (which measure), how it is broken down, the exact period with dates (e.g. 1-30 Sep 2026) and which
  date it is based on, any filters, and top-N or sorting.
- If a sensible reading exists, set needs_clarification to false and write the query. Where you had
  to pick a default (period, date, which measure), say so in the understanding.
- Set needs_clarification to true only when you cannot pick a sensible reading: the question names
  nothing you can measure, or it could mean very different things that would give very different
  numbers, and neither the glossary, the business notes nor earlier questions settle it. Then leave
  query empty, ask ONE short question in clarifying_question and give 2-4 short answer options.
"""

RULES = {"DAX": DAX_RULES + ANSWER_RULES, "SQL": SQL_RULES + ANSWER_RULES}

QUERY_TOOL = {
    "name": "submit_query",
    "description": "Submit the query that answers the user's question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "understanding": {"type": "string", "description": "The question restated precisely: measure, breakdown, exact period and date used, filters."},
            "needs_clarification": {"type": "boolean"},
            "clarifying_question": {"type": "string", "description": "Only when needs_clarification is true, else empty."},
            "options": {"type": "array", "items": {"type": "string"}, "description": "2-4 short answers to the clarifying question, else empty."},
            "query": {"type": "string", "description": "The complete query, or empty when asking for clarification."},
            "explanation": {"type": "string", "description": "One plain-English sentence: what the query returns and any assumption made."},
        },
        "required": ["understanding", "needs_clarification", "clarifying_question", "options", "query", "explanation"],
    },
}

CHART_TOOL = {
    "name": "submit_chart",
    "description": "Choose how to display the result and answer the question in words.",
    "input_schema": {
        "type": "object",
        "properties": {
            "chart_type": {"type": "string", "enum": charts.CHART_TYPES,
                           "description": (
                               "Pick the chart that answers the question best: map when the breakdown is by "
                               "country; line (or area) for trends over time; donut for 2-6 parts of a whole; "
                               "treemap for shares across many parts; horizontal_bar for rankings / top N or long "
                               "names; bar to compare a few categories; stacked_bar for a category split by a "
                               "second one with few values; heatmap for two breakdowns with many values (e.g. "
                               "market by month); scatter to relate two numbers; table when a chart would not "
                               "help (e.g. a single row with many numbers). Never put two measures with very "
                               "different scales on one chart.")},
            "x": {"type": "string", "description": "Column for the x-axis, the labels, or the countries (map). Exact column name."},
            "y": {"type": "array", "items": {"type": "string"}, "description": "Numeric column(s) to plot. Exact column names."},
            "color": {"type": "string", "description": "Second breakdown column (series of a line / stacked bar, rows of a heatmap), or empty."},
            "title": {"type": "string"},
            "summary": {"type": "string", "description": "2-3 sentences answering the question with the key numbers. Plain English."},
        },
        "required": ["chart_type", "title", "summary"],
    },
}


MAX_CHECK_ROUNDS = 5  # rounds of data checks (tool calls) before Claude must answer

CHECK_RULES = """Before writing the query, check the data with your tools (at most 5 rounds of checks):
- For every word or name in the question that refers to a value (a status, market, country, channel,
  customer, supplier, product...), call find_values to see which columns contain it, the exact value and
  how much data it has. Look up several words in the same turn.
- If a phrase matches values in more than one column with different meanings (e.g. a market and a
  country), or matches only a value with no data, ask: set needs_clarification and give the real values
  as options, e.g. "Market = UAE". Don't ask if an Agreed glossary entry or the business notes settle
  it; a Draft glossary entry does not settle which values to filter on. If several things are unclear,
  ask about the most important one first.
- If you are unsure a filter returns data, check with preview_query before answering.
- Filter only on exact values you found."""


def _structured_call(system: list, tool: dict, user_text: str, tools: list | None = None,
                     run_tool=None, on_step=None) -> dict:
    """Ask Claude for JSON matching the tool's schema. (Forcing a tool call with tool_choice
    is not supported on current Claude models, so this uses structured outputs instead.)
    With tools, Claude may first call them (e.g. to look up values); run_tool(name, input) answers."""
    schema = {**tool["input_schema"], "additionalProperties": False}
    messages = [{"role": "user", "content": user_text}]
    for check_round in range(MAX_CHECK_ROUNDS + 1):
        extra = {}
        if tools and run_tool:
            extra["tools"] = tools
            if check_round == MAX_CHECK_ROUNDS:
                extra["tool_choice"] = {"type": "none"}  # enough checking: answer now
        response = _get_client().messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=16000,  # Claude thinks before answering, and thinking counts toward this limit
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
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


def question_to_query(question: str, schema: str, notes: str, today: str, language: str = "DAX",
                      context: list[dict] | None = None,
                      failed_query: str | None = None, error: str | None = None,
                      clarification: tuple[str, str] | None = None, instructions: str = "",
                      tools: list | None = None, run_tool=None, on_step=None) -> dict:
    """clarification = (question Claude asked, the user's answer). instructions = extra
    requirements, e.g. for a dashboard chart. tools + run_tool let Claude check the data first
    (on_step(name, input) reports each check). A result with needs_clarification has no query."""
    rules = RULES[language].replace("MAX_ROWS", str(config.MAX_ROWS)).replace("TODAY_DATE", today)
    system_text = rules + "\n\n" + schema
    if notes.strip():
        system_text += "\n\n## Business notes from the user\n" + notes
    # The schema is the same every time, so cache it (cheaper and faster on repeat questions).
    system = [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]

    parts = []
    for prev in (context or [])[-3:]:
        parts.append(f"Earlier question: {prev['question']}\nEarlier query:\n{prev['query']}")
    parts.append(f"Question: {question}")
    if clarification:
        parts.append(f"You asked: {clarification[0]}\nThe user answered: {clarification[1]}\n"
                     "Use this answer. Only ask again about something different that is still unclear.")
    if instructions:
        parts.append(instructions)
    if failed_query:
        parts.append(f"Your previous query failed.\nQuery:\n{failed_query}\n\nError:\n{error}\n\n"
                     "Fix the query (check names against the schema). Do not ask for clarification.")
    if tools and run_tool:
        parts.append(CHECK_RULES)
    result = _structured_call(system, QUERY_TOOL, "\n\n".join(parts), tools, run_tool, on_step)
    if result.get("needs_clarification") and result.get("clarifying_question") and not failed_query:
        result["query"] = ""
        return result
    if not result.get("query", "").strip():  # checked the data but gave no query: ask once more
        parts.append("You did not return a query. Using what you found, write the query now "
                     "(needs_clarification false).")
        result = _structured_call(system, QUERY_TOOL, "\n\n".join(parts))
    result["needs_clarification"] = False
    if language == "DAX":
        validate_dax(result.get("query", ""))
    return result


def dashboard_instructions(language: str, date_column: str, kpi: bool, base_query: str = "") -> str:
    """Extra requirements for a dashboard chart: the dashboard, not the question, sets the period."""
    lines = ["This query is for a dashboard chart that is re-run for whatever period the user picks."]
    if base_query:
        lines.append("Start from this query, which answered the question in a chat. Keep its measures, "
                     f"breakdown, sorting and top-N, but change the period as described below:\n{base_query}")
    if date_column and language == "DAX":
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
    lines.append("Set needs_clarification to false.")
    return "\n".join(lines)


def validate_dax(dax: str) -> None:
    if not dax.strip():
        raise RuntimeError("Claude did not return a query. Try rephrasing the question.")
    body = re.sub(r"(--|//).*?$", "", dax, flags=re.MULTILINE)  # drop comment lines
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL).strip()
    if not re.match(r"^(DEFINE|EVALUATE)\b", body, flags=re.IGNORECASE):
        raise ValueError("Generated query does not start with EVALUATE/DEFINE, so it was not run.")


def describe_result(question: str, df: pd.DataFrame) -> dict:
    sample = df.head(60).to_csv(index=False)
    col_info = ", ".join(f"{c} ({'number' if pd.api.types.is_numeric_dtype(df[c]) else 'text/date'})"
                         for c in df.columns)
    system = [{"type": "text", "text": (
        "You present query results for business users. Pick the clearest chart and answer "
        "the question in plain English using the numbers shown. Do not invent numbers.")}]
    hint = charts.suggest(df)
    user = (f"Question: {question}\n\nResult has {len(df)} rows. Columns: {col_info}\n"
            f"From the shape of the data the best fit looks like: {hint['chart_type']} "
            f"(x={hint['x']!r}, color={hint['color']!r}). Use it unless another chart answers the question better.\n\n"
            f"First rows (CSV):\n{sample}")
    spec = _structured_call(system, CHART_TOOL, user)
    spec.setdefault("y", [])
    return charts.fit(df, spec)
