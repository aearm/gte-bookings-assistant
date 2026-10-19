r"""Bookings Assistant for Claude (Claude Desktop, Claude Code): a connector (MCP server) that gives any Claude
conversation on this computer the cubes' knowledge and the dashboards, without the app's Claude key - the
conversation's own Claude reads the data layer, checks its queries on the cubes and adds or changes dashboard
charts, following the bookings-dashboards skill (skills/bookings-dashboards) for how to draw them.

Claude starts it by itself once it is connected:  install\connect_claude.ps1  (setup does it when Claude is
installed). By hand:  .venv\Scripts\python.exe mcp_server.py  (speaks MCP on stdin/stdout).
The work behind each tool is in assistant_tools.py."""
import contextlib
import functools
import io
import logging
import os
import sys
from pathlib import Path
from typing import Any, Literal

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # see start_server.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

SKILL = Path(__file__).resolve().parent / "skills" / "bookings-dashboards"

INSTRUCTIONS = """Bookings Assistant: the company's live bookings data (Analysis Services cubes: bookings, sales, \
searches, API requests, suppliers, hotels...) and the dashboards of the Bookings Assistant app.
- Before answering a question about the data or making a chart, call get_knowledge once in the conversation (the \
cubes, which cube for what, how they join, and the rules for writing queries), then get_cube_details for the cubes \
you use and find_values for every name or value you filter on. Check numbers with run_query.
- To add or change dashboard charts, follow the bookings-dashboards skill; if it isn't loaded, call \
get_dashboard_guide first. Charts are checked on the cubes before they are saved, and the app draws them.
- Give the user the dashboard's link after changing it. Delete dashboards or charts only when the user asks."""

mcp = FastMCP("bookings-assistant", instructions=INSTRUCTIONS, log_level="WARNING")
log = logging.getLogger("mcp_server")
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
REMOVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)


def tool(annotations: ToolAnnotations):
    """A tool whose printing can't break the conversation (stdout carries MCP) and whose problems come back to
    Claude as plain sentences."""
    def wrap(fn):
        @functools.wraps(fn)
        def run(*args, **kwargs):
            import assistant_tools
            from errors import friendly
            with contextlib.redirect_stdout(sys.stderr):
                try:
                    return fn(*args, **kwargs)
                except assistant_tools.ToolError:
                    raise
                except Exception as exc:
                    log.exception("Tool %s failed", fn.__name__)
                    raise assistant_tools.ToolError(friendly(exc)) from exc
        return mcp.tool(annotations=annotations)(run)
    return wrap


# ---------------------------------------------------------------- what Claude sends --

class Step(BaseModel):
    name: str = Field(description="Short lowercase name (letters, digits, _): the step's table name in combine_sql.")
    cube: str = Field(description="Exact cube name, as in the knowledge.")
    query: str = Field(description="The query for that cube (DAX: EVALUATE ...). In a dashboard chart its date is "
                                   "filtered with @START and @END; dashboard filters are @F_<KEY> placeholders.")


class Format(BaseModel):
    column: str = Field(description="Exact number column of the result.")
    d3_format: str = Field(description="d3 format: ',.0f' whole numbers, ',.2f' averages, '.1%' fractions as "
                                       "percent, '~s' compact (4.5M).")
    prefix: str = Field("", description="e.g. 'AED ' for money.")
    suffix: str = Field("", description="e.g. '%' for numbers already 0-100, ' nights'.")


class Style(BaseModel):
    formats: list[Format] = Field(default_factory=list, description="One per number column shown.")
    x_title: str | None = None
    y_title: str | None = Field(None, description="The measure and its unit, e.g. 'Sales (AED)'.")
    sort: Literal["value_desc", "value_asc", "label", "none"] | None = None
    show_values: bool | None = Field(None, description="Write each value on its bar or slice (up to ~12 bars).")
    label_angle: Literal[0, -30, -45, -90] | None = None
    legend: Literal["top", "right", "bottom", "none"] | None = None
    log_scale: bool | None = None
    measures: Literal["auto", "one_chart", "panels"] | None = Field(
        None, description="Several measures: auto (one panel each when sizes differ), one_chart, panels.")
    lower_is_better: bool | None = Field(None, description="Headline numbers: a rise shows red (e.g. look-to-book).")


ChartType = Literal["kpi", "bar", "horizontal_bar", "stacked_bar", "line", "area", "donut", "treemap", "map",
                    "heatmap", "scatter", "table", "custom"]


class Chart(BaseModel):
    title: str = Field(description="What the chart shows, without dates (the dashboard sets the period).")
    question: str = Field("", description="What it answers, in a sentence (shown when hovering the chart).")
    chart_type: ChartType
    steps: list[Step] = Field(description="One query per cube; most charts have one step.")
    combine_sql: str = Field("", description="Several steps: ONE DuckDB SELECT joining them by their names.")
    x: str = Field("", description="Column for the categories, dates or countries (map). Empty for kpi.")
    y: list[str] = Field(default_factory=list, description="Number column(s) to plot.")
    color: str = Field("", description="Second breakdown column (series, stacks, heatmap rows), or empty.")
    width: Literal["half", "full"] | None = Field(None, description="half (default) or full width.")
    style: Style | None = None
    compare: bool = Field(True, description="False: never next to the comparison period.")
    date_column: str = Field("", description="The date the period filters (default: the cube's main date).")
    custom: dict[str, Any] | None = Field(None, description="chart_type custom only: an ECharts option whose data "
                                                            "point at result columns, {\"col\": \"Sales\"}.")


class ChartChanges(BaseModel):
    title: str | None = None
    question: str | None = None
    chart_type: ChartType | None = None
    steps: list[Step] | None = None
    combine_sql: str | None = None
    x: str | None = None
    y: list[str] | None = None
    color: str | None = None
    width: Literal["half", "full"] | None = None
    style: Style | None = Field(None, description="Replaces the whole style.")
    compare: bool | None = None
    date_column: str | None = None
    custom: dict[str, Any] | None = None


class FilterOptions(BaseModel):
    cube: str = Field(description="The cube the values come from.")
    query: str = Field(description="Query listing the values with data (filter its date with @START / @END: it runs "
                                   "for the last year), biggest first, e.g. TOPN by sales.")
    value: str = Field(description="The result column whose value fills the placeholder (e.g. a code).")
    label: str = Field("", description="How a value is shown, with {Column} parts, e.g. '{Customer} - {Code}'.")
    title_case: bool = False


class Filter(BaseModel):
    key: str = Field(description="Short lowercase key, e.g. client: queries then hold @F_CLIENT.")
    label: str = Field(description="Shown above the dashboard, e.g. Client.")
    options: FilterOptions


def _dump(model) -> dict:
    return model.model_dump(exclude_none=True) if model is not None else {}


def _chart(chart: Chart) -> dict:
    spec = chart.model_dump(exclude_none=True)
    spec["steps"] = [s.model_dump() for s in chart.steps]
    if chart.style is not None:
        spec["style"] = _dump(chart.style)
    return spec


# ---------------------------------------------------------------- knowledge --

@tool(READ)
def get_knowledge() -> str:
    """The data layer: every cube in a short card (what it is for, its measures, dates and dimensions), which
    cube to use for what, the dimensions the cubes share (how to join them), today's date, and the rules for
    writing queries and dashboard charts. Read it once per conversation, before anything else."""
    import assistant_tools
    return assistant_tools.knowledge()


@tool(READ)
def get_cube_details(cube: str, full: bool = False) -> str:
    """One cube's exact measures, columns (with the helper and sort columns a query needs), values with how much
    data each has, business notes, glossary and meaning rules. Read it before writing a query on that cube.
    full: the whole structure, when the short one lacks a column."""
    import assistant_tools
    return assistant_tools.cube_details(cube, full)


@tool(READ)
def find_values(text: str, cube: str = "", column: str = "") -> str:
    """Where a word or name appears in the data (a country, market, client, supplier, hotel, status...): every
    cube and column, the exact value as stored and how much data it has. Use it before filtering on any value.
    cube / column: only there (needed for columns listed as not indexed)."""
    import assistant_tools
    return assistant_tools.find_values(text, cube, column)


@tool(READ)
def get_join_path(cubes: list[str]) -> str:
    """How two or more cubes join: their shared dimensions and the columns to join on, best first."""
    import assistant_tools
    return assistant_tools.join_path(cubes)


@tool(READ)
def run_query(steps: list[Step], combine_sql: str = "", start: str = "", end: str = "",
              filters: dict[str, str] | None = None) -> str:
    """Run a plan on the cubes and see its result (columns, row count, first rows). start / end (YYYY-MM-DD, end
    included) fill @START / @END, else the dashboard's default period; filters fill @F_ placeholders, e.g.
    {"CLIENT": "1042"}."""
    import assistant_tools
    return assistant_tools.run_query([s.model_dump() for s in steps], combine_sql, start, end, filters)


@tool(READ)
def get_dashboard_guide() -> str:
    """How to make good dashboard charts for this app (the bookings-dashboards skill): the chart types and when to
    use each, how to describe a chart, formats, filters and the workflow. Read it before adding or changing
    charts if the skill isn't loaded."""
    parts = [(SKILL / "SKILL.md").read_text(encoding="utf-8")]
    for ref in sorted((SKILL / "references").glob("*.md")):
        parts.append(f"\n\n---\n# {ref.name}\n\n" + ref.read_text(encoding="utf-8"))
    return "".join(parts)


# ---------------------------------------------------------------- dashboards --

@tool(READ)
def list_dashboards() -> str:
    """The app's dashboards: id, name, how many charts, filters, and the link to open each."""
    import assistant_tools
    return assistant_tools.list_dashboards()


@tool(READ)
def get_dashboard(dashboard_id: str) -> dict:
    """A dashboard with its filters and every chart as add_chart takes it (id, title, chart_type, steps, x, y,
    style...): read it before changing a chart."""
    import assistant_tools
    return assistant_tools.get_dashboard(dashboard_id)


@tool(WRITE)
def preview_chart(dashboard_id: str, chart: Chart) -> str:
    """Check a chart without saving it: runs it for the dashboard's default period and draws it as the dashboard
    would. Returns the numbers, any problem, and the ECharts option the app draws."""
    import assistant_tools
    return assistant_tools.preview_chart(dashboard_id, _chart(chart))


@tool(WRITE)
def add_chart(dashboard_id: str, chart: Chart, position: int | None = None) -> str:
    """Add a chart to a dashboard. It is run on the cubes first and saved only if it runs and draws; the answer
    has its first numbers and the dashboard's link. position: its place (0 = first), else last."""
    import assistant_tools
    return assistant_tools.add_chart(dashboard_id, _chart(chart), position)


@tool(WRITE)
def update_chart(dashboard_id: str, chart_id: str, changes: ChartChanges) -> str:
    """Change a chart: only the settings given change (steps replace all its steps; style replaces its style).
    Checked on the cubes before it is saved."""
    import assistant_tools
    spec = changes.model_dump(exclude_none=True)
    if changes.steps is not None:
        spec["steps"] = [s.model_dump() for s in changes.steps]
    if changes.style is not None:
        spec["style"] = _dump(changes.style)
    return assistant_tools.update_chart(dashboard_id, chart_id, spec)


@tool(WRITE)
def move_chart(dashboard_id: str, chart_id: str, position: int) -> str:
    """Put a chart at a place on its dashboard: 0 = first (headline numbers come first, then the trend)."""
    import assistant_tools
    return assistant_tools.move_chart(dashboard_id, chart_id, position)


@tool(WRITE)
def copy_chart(dashboard_id: str, chart_id: str, to_dashboard_id: str) -> str:
    """Copy a chart to another dashboard."""
    import assistant_tools
    return assistant_tools.copy_chart(dashboard_id, chart_id, to_dashboard_id)


@tool(REMOVE)
def delete_chart(dashboard_id: str, chart_id: str) -> str:
    """Remove a chart from a dashboard (only when the user asked)."""
    import assistant_tools
    return assistant_tools.delete_chart(dashboard_id, chart_id)


@tool(WRITE)
def create_dashboard(name: str) -> str:
    """A new, empty dashboard; returns its id and link."""
    import assistant_tools
    return assistant_tools.create_dashboard(name)


@tool(WRITE)
def copy_dashboard(dashboard_id: str, name: str) -> str:
    """A copy of a dashboard (charts and filters) under a new name."""
    import assistant_tools
    return assistant_tools.copy_dashboard(dashboard_id, name)


@tool(WRITE)
def rename_dashboard(dashboard_id: str, name: str) -> str:
    """Rename a dashboard."""
    import assistant_tools
    return assistant_tools.rename_dashboard(dashboard_id, name)


@tool(WRITE)
def set_dashboard_filters(dashboard_id: str, filters: list[Filter]) -> str:
    """Set the filters above a dashboard (e.g. a client picker); [] removes them. Each filter's values come from its
    own query (checked now); its charts' queries use @F_<KEY>."""
    import assistant_tools
    return assistant_tools.set_filters(dashboard_id, [f.model_dump() for f in filters])


@tool(REMOVE)
def delete_dashboard(dashboard_id: str) -> str:
    """Delete a dashboard and its charts (only when the user asked for exactly this)."""
    import assistant_tools
    return assistant_tools.delete_dashboard(dashboard_id)


def _own_pipes():
    """Claude's messages come on stdin and answers go on stdout. On Windows, while a pipe is being read every
    other use of it waits - and each library a tool loads (numpy, the cube connector) asks Windows about the
    standard handles as it starts, so the tool would hang until Claude's next message. The pipes are read and
    written through handles of our own; the standard ones become NUL (in) and stderr (out), which also keeps
    anything printed out of the conversation."""
    pipe_in, pipe_out = os.dup(0), os.dup(1)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.dup2(2, 1)
    os.close(null)
    return (io.TextIOWrapper(os.fdopen(pipe_in, "rb"), encoding="utf-8"),
            io.TextIOWrapper(os.fdopen(pipe_out, "wb"), encoding="utf-8", write_through=True))


async def _serve() -> None:
    import anyio
    from mcp.server.stdio import stdio_server
    reader, writer = _own_pipes()
    async with stdio_server(stdin=anyio.wrap_file(reader), stdout=anyio.wrap_file(writer)) as (read, write):
        server = mcp._mcp_server
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(asctime)s %(name)s: %(message)s")
    import anyio
    anyio.run(_serve)


if __name__ == "__main__":
    main()
