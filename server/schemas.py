"""The shapes the API sends and receives (docs/api.md). The React app's web/src/api/types.ts mirrors
these. Fields beyond the contract are marked "extra": the app may use them, nothing relies on them."""
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

PeriodMode = Literal["dashboard", "own", "fixed"]
Width = Literal["half", "full"]


# ---------------------------------------------------------------- shared shapes --

class Column(BaseModel):
    name: str
    type: Literal["number", "text", "date"]
    format: dict[str, Any] | None = None  # extra: how the chart writes this column's numbers (chart_options x-format)


class Table(BaseModel):
    columns: list[Column]
    rows: list[list[Any]]
    row_count: int
    truncated: bool


class Chart(BaseModel):
    kind: str
    option: dict[str, Any] | None = None
    title: str = ""
    summary: str = ""
    note: str = ""


class Period(BaseModel):
    start: date
    end: date
    label: str
    preset: str = ""


class Comparison(Period):
    mode: str = ""   # extra: previous, last_year, custom
    name: str = ""   # extra: for "+12% vs <name>": "the 7 days before", "last year"


class Ok(BaseModel):
    ok: bool = True


# ---------------------------------------------------------------- session & app --

class SignIn(BaseModel):
    password: str
    keep: bool = False


class FirstPassword(BaseModel):
    password: str


class SessionState(BaseModel):
    admin: bool
    has_admin_password: bool = True


class Info(BaseModel):
    version: str
    data_source: str
    ready: bool
    why: str
    scopes: list[dict[str, str]]
    example_questions: list[str]
    defaults: dict[str, str]
    chart_types: list[dict[str, str]] = []   # extra: for the chart type pickers
    width_choices: list[str] = ["half", "full"]  # extra


# ---------------------------------------------------------------- chat --

class NewConversation(BaseModel):
    scope: str = ""


class Clarification(BaseModel):
    question: str = ""
    answer: str


class Ask(BaseModel):
    question: str = ""
    clarification: Clarification | None = None


class ChartRequest(BaseModel):
    request: str


class Verify(BaseModel):
    verified: bool = True


class PeriodRef(BaseModel):
    phrase: str = ""
    start: str = ""
    end: str = ""


class Clarify(BaseModel):
    question: str
    options: list[str] = []
    answered: bool = False  # extra


class ModeChoice(BaseModel):
    mode: PeriodMode
    label: str
    instant: bool


class Turn(BaseModel):
    id: str
    question: str
    understanding: str = ""
    query: str = ""
    cubes: list[str] = []
    explanation: str = ""
    notes: list[str] = []
    periods: list[PeriodRef] = []
    table: Table | None = None
    chart: Chart | None = None
    clarify: Clarify | None = None
    error: str | None = None
    answer_id: int | None = None
    details: str | None = None          # extra: technical text of an error
    language: str = ""                  # extra: DAX or SQL (the query viewer's label)
    verified: bool = False              # extra
    asked: str = ""                     # extra: when its numbers were read
    dashboard_modes: list[ModeChoice] = []  # extra: how it can go on a dashboard, suggested first


class Pending(BaseModel):
    """The question being answered right now and its progress so far."""
    question: str
    steps: list[str]


class ConversationOut(BaseModel):
    id: str
    scope: str
    turns: list[Turn]
    pending: Pending | None = None


class ChartOut(BaseModel):
    chart: Chart


class HistoryEntry(BaseModel):
    time: str
    question: str
    rows: int = 0
    title: str = ""


# ---------------------------------------------------------------- dashboards --

class DashboardName(BaseModel):
    name: str = Field(min_length=1)


class PeriodPick(BaseModel):
    """The dashboard's period at the time of a change (optional; the defaults otherwise). Used when a chart
    has to be tried out or its numbers kept for a period."""
    start: date | None = None
    end: date | None = None
    preset: str = ""
    compare: str = ""
    cstart: date | None = None
    cend: date | None = None


class NewChart(PeriodPick):
    question: str = Field(min_length=1)
    title: str = ""
    chart_type: str = "auto"
    width: Width = "half"
    cube: str = ""
    date_column: str | None = None
    period_mode: PeriodMode = "dashboard"
    chart_request: str = ""  # extra: a custom chart's description


class FromAnswer(PeriodPick):
    conversation_id: str
    turn_id: str
    period_mode: PeriodMode | None = None  # None: the suggested way
    title: str | None = None
    width: Width | None = None
    chart_type: str | None = None          # extra


class FromConversation(PeriodPick):
    conversation_id: str
    name: str = Field(min_length=1)
    turn_ids: list[str] | None = None      # extra: only these answers (default: every answer with a chart)


class ChartChanges(PeriodPick):
    title: str | None = None
    chart_type: str | None = None
    width: Width | None = None
    date_column: str | None = None
    period_mode: PeriodMode | None = None
    compare: bool | None = None            # show the dashboard's comparison on this chart
    question: str | None = None
    chart_request: str | None = None       # extra
    query: str | None = None               # extra: the advanced query edit (one-step charts)


class Restyle(PeriodPick):
    request: str = Field(min_length=1)


class Send(BaseModel):
    to: str
    move: bool = False
    name: str = ""                         # extra: with to="new", the new dashboard's name


class MoveStep(BaseModel):
    step: Literal[-1, 1]


class Starter(PeriodPick):
    cube: str


class PeriodInfo(BaseModel):
    mode: PeriodMode
    label: str


class ChartMeta(BaseModel):
    id: str
    title: str
    question: str = ""
    chart_type: str
    width: Width = "half"
    cubes: list[str] = []
    date_column: str = ""
    period: PeriodInfo
    compares: bool = False
    lower_is_better: bool = False  # extra: a headline number that is better when it falls (e.g. look-to-book)
    caption: str = ""            # extra: the card's line ("Bookings + Payments · Dates: Create Date")
    date_label: str = ""         # extra
    sources: list[str] = []      # extra: the cubes' labels
    compare_on: bool = True      # extra: the admin's switch for the comparison
    chart_request: str = ""      # extra
    query: str = ""              # extra
    query_editable: bool = False  # extra: one-step plans can be edited by hand


class FilterMeta(BaseModel):
    """A filter above a dashboard's charts (e.g. a client); its values come from /dashboards/{id}/filters."""
    key: str
    label: str


class Dashboard(BaseModel):
    id: str
    name: str
    charts: list[ChartMeta]
    filters: list[FilterMeta] = []
    failed: list[dict[str, str]] = []  # extra (from-conversation): charts that couldn't be added, and why


class DashboardSummary(BaseModel):
    id: str
    name: str
    charts: int


class Kpi(BaseModel):
    value: float | None = None
    text: str = "-"
    change: float | None = None
    change_text: str = ""
    prev_text: str = ""     # extra: the comparison's number
    prev_label: str = ""    # extra: the comparison's dates


class ChartResult(BaseModel):
    chart: Chart | None = None
    table: Table | None = None
    prev_table: Table | None = None
    kpi: Kpi | None = None
    error: str | None = None
    details: str | None = None
    period_label: str = ""


class DataAsOf(BaseModel):
    text: str = ""
    per_cube: dict[str, str] = {}


class Results(BaseModel):
    period: Period
    compare: Comparison | None = None
    data_as_of: DataAsOf
    charts: dict[str, ChartResult]
    updating: bool
    filters: dict[str, str] = {}  # the value each filter had (the default when none was asked for)
    setup: str = ""  # why there are no numbers yet (the cube server isn't set up): shown once on the page


class FilterOption(BaseModel):
    value: str
    label: str


class FilterChoices(BaseModel):
    key: str
    label: str
    options: list[FilterOption]
    default: str
    error: str = ""


# ---------------------------------------------------------------- meaning layer, cubes, settings --

class GlossaryRows(BaseModel):
    rows: list[dict[str, Any]]


class DecisionAnswer(BaseModel):
    answer: str = Field(min_length=1)


class EnabledCubes(BaseModel):
    names: list[str]


class LayerBuild(BaseModel):
    cubes: list[str] | None = None
    only_changed: bool = False


class SetupAnswer(BaseModel):
    index: int
    option: int | None = None
    custom: str = ""


class SetupSkip(BaseModel):
    index: int


class SetupConfirm(BaseModel):
    indexes: list[int]
    rejected: list[int] = []


class JobStarted(BaseModel):
    job: str


class ApiKey(BaseModel):
    key: str


class ServerLogin(BaseModel):
    server: str
    database: str | None = None
    username: str | None = None
    password: str = ""


class AdminPassword(BaseModel):
    current: str
    new: str
