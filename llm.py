"""Claude turns questions into DAX, and results into a chart + short answer."""
import json
import re

import anthropic
import pandas as pd

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
- "This year", "last month" etc.: today's date is TODAY_DATE.
- If the question is ambiguous, make a reasonable choice and say what you assumed in the explanation.
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
- "This year", "last month" etc.: today's date is TODAY_DATE (use DATE 'TODAY_DATE', not current_date).
- Use the listed example values to match filters exactly (e.g. country or status spellings).
- If the question is ambiguous, make a reasonable choice and say what you assumed in the explanation.
- If an earlier question is given as context, treat the new question as a follow-up to it.
"""

RULES = {"DAX": DAX_RULES, "SQL": SQL_RULES}

QUERY_TOOL = {
    "name": "submit_query",
    "description": "Submit the query that answers the user's question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The complete query."},
            "explanation": {"type": "string", "description": "One plain-English sentence: what the query returns and any assumption made."},
        },
        "required": ["query", "explanation"],
    },
}

CHART_TOOL = {
    "name": "submit_chart",
    "description": "Choose how to display the result and answer the question in words.",
    "input_schema": {
        "type": "object",
        "properties": {
            "chart_type": {"type": "string", "enum": ["bar", "horizontal_bar", "line", "area", "pie", "scatter", "table"],
                           "description": "line/area for trends over time, bar for comparing categories, horizontal_bar for long category names or rankings, pie only for 2-6 parts of a whole, table when a chart would not help."},
            "x": {"type": "string", "description": "Column for the x-axis (or pie labels). Must be an exact column name."},
            "y": {"type": "array", "items": {"type": "string"}, "description": "Numeric column(s) to plot. Exact column names."},
            "color": {"type": "string", "description": "Optional column to split into series (exact name), or empty."},
            "title": {"type": "string"},
            "summary": {"type": "string", "description": "2-3 sentences answering the question with the key numbers. Plain English."},
        },
        "required": ["chart_type", "title", "summary"],
    },
}


def _structured_call(system: list, tool: dict, user_text: str) -> dict:
    """Ask Claude for JSON matching the tool's schema. (Forcing a tool call with tool_choice
    is not supported on current Claude models, so this uses structured outputs instead.)"""
    schema = {**tool["input_schema"], "additionalProperties": False}
    response = _get_client().messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,  # Claude thinks before answering, and thinking counts toward this limit
        system=system,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": user_text}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to answer this question. Try rephrasing it.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Claude's answer was cut off. Try a simpler or narrower question.")
    for block in response.content:
        if block.type == "text":
            return json.loads(block.text)
    raise RuntimeError("Claude did not return a result. Try rephrasing the question.")


def question_to_query(question: str, schema: str, notes: str, today: str, language: str = "DAX",
                      context: list[dict] | None = None,
                      failed_query: str | None = None, error: str | None = None) -> dict:
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
    if failed_query:
        parts.append(f"Your previous query failed.\nQuery:\n{failed_query}\n\nError:\n{error}\n\n"
                     "Fix the query (check names against the schema).")
    result = _structured_call(system, QUERY_TOOL, "\n\n".join(parts))
    if language == "DAX":
        validate_dax(result.get("query", ""))
    return result


def validate_dax(dax: str) -> None:
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
    user = (f"Question: {question}\n\nResult has {len(df)} rows. Columns: {col_info}\n\n"
            f"First rows (CSV):\n{sample}")
    spec = _structured_call(system, CHART_TOOL, user)
    spec.setdefault("y", [])
    return spec
