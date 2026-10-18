"""The dashboards every installation starts with: a business overview for the executives, then one
market (the clients' country), one destination (the hotel's country), one client and one supplier
connection in detail. Their queries are written here by hand (no Claude), on the
Bookings cube (sales, profit, bookings), Hotel Sales (hotel bookings by the hotel's country and city),
Statistics Zone (searches), Statistics History Client (client API requests, look-to-book), Statistics
History Supplier (requests sent to suppliers), Statistics Hotel Client (hotel-level requests and
availability) and History Hotel Locks (hotel options that failed in the booking flow).

Where things are: the client (agency) is 'Customers' - its country is the market; the guests' nationality
is 'Countries'[Country] in Bookings and Hotel Sales (as the agency sent it with the booking; checked on the
data - it is not the destination); the destination is the hotel's country, 'Hotels'[Hotel Country] in Hotel
Sales (Bookings has only 'Areas', which mixes cities, regions and countries). The destination and market views
put them side by side: who travels (nationality), where to (destination) and who booked them (market).

Each chart follows the dashboard's period (@START / @END) and comparison. The detailed dashboards have a
filter (dashboards.py "dashboard filters"): their queries hold @F_CLIENT (a customer code), @F_MARKET (a
customer country), @F_DESTINATION (a hotel country) or @F_SUPPLIER (a supplier connection code), filled
with the value picked above the charts; the list to pick from comes from the filter's own query (those
with sales in the last year, biggest first - the first is the default). No customer is named here: the
repository is public.

Shown in this order on each dashboard, to read top to bottom: the headline numbers, the trend, who buys,
where the guests go, what is bought, then demand (searches, API requests) and look-to-book.
Raise VERSION after changing a dashboard: installations then get the new version of it
(dashboards.ensure_builtin), replacing the old one's charts."""
from plans import Plan, Step

BOOKINGS = "GlobalTravelEngine - Bookings"
REQUESTS = "GlobalTravelEngine - Statistics History Client"
SEARCHES = "GlobalTravelEngine - Statistics Zone"
SUPPLIER_REQUESTS = "GlobalTravelEngine - Statistics History Supplier"
HOTEL_REQUESTS = "GlobalTravelEngine - Statistics Hotel Client"
LOCKS = "GlobalTravelEngine - History Hotel Locks"
HOTEL_SALES = "GlobalTravelEngine - Sales Per Owned Hotels"  # hotel bookings, owned and third-party hotels

VERSION = 6


# ---------------------------------------------------------------- query pieces --

def _within(column: str) -> str:
    """The dashboard's period on a date column (@END is the day after the last day)."""
    return f"KEEPFILTERS(FILTER(ALL({column}), {column} >= @START && {column} < @END))"


def _where(column: str, helper: str, condition: str) -> str:
    """A filter on a column of a multidimensional cube, which needs its key column alongside."""
    return f"KEEPFILTERS(FILTER(ALL({column}, {helper}), {condition}))"


TEST = '"Market for Testing Purposes"'  # the test agencies' market: never in a business number

# the filters of each cube, by scope: everything, or one client, market (the clients' country), destination
# (the hotel's country) or supplier connection
_SCOPES = {
    BOOKINGS: {
        "date": "'Calendar'[Date]",
        "real": _where("'Customers'[Market]", "'Customers'[Market.UniqueName]", f"'Customers'[Market] <> {TEST}"),
        "client": _where("'Customers'[Code]", "'Customers'[Code.Key0]", "'Customers'[Code] = @F_CLIENT"),
        "market": _where("'Customers'[Customer Country]", "'Customers'[Customer Country.UniqueName]",
                         "'Customers'[Customer Country] = @F_MARKET"),
        # the connection the booking came through: the same codes as the supplier-side cubes
        "supplier": _where("'Product Type'[Module Code]", "'Product Type'[Module Code.UniqueName]",
                           "'Product Type'[Module Code] = @F_SUPPLIER"),
    },
    HOTEL_SALES: {
        "date": "'Booking Date'[Booking Date]",
        "real": _where("'Customers'[Market]", "'Customers'[Market.UniqueName]", f"'Customers'[Market] <> {TEST}"),
        # the same client codes as Bookings, with GTE in front
        "client": _where("'Customers'[Id Cli]", "'Customers'[Id Cli.UniqueName]",
                         "'Customers'[Id Cli] = \"GTE\" & @F_CLIENT"),
        "market": _where("'Customers'[Default Country]", "'Customers'[Default Country.UniqueName]",
                         "'Customers'[Default Country] = @F_MARKET"),
        "destination": _where("'Hotels'[Hotel Country]", "'Hotels'[Hotel Country.UniqueName]",
                              "'Hotels'[Hotel Country] = @F_DESTINATION"),
        "supplier": _where("'Modules'[Module Code]", "'Modules'[Module Code.UniqueName]",
                           "'Modules'[Module Code] = @F_SUPPLIER"),
    },
    SUPPLIER_REQUESTS: {
        "date": "'Calendario'[Fecha]",
        "real": _where("'Cliente'[Market]", "'Cliente'[Market.UniqueName]", f"'Cliente'[Market] <> {TEST}"),
        "supplier": _where("'Suppliers'[Supplier Code]", "'Suppliers'[Supplier Code.UniqueName]",
                           "'Suppliers'[Supplier Code] = @F_SUPPLIER"),
    },
    HOTEL_REQUESTS: {
        "date": "'Request Calendar'[Request Day]",
        "real": _where("'Customers'[Market]", "'Customers'[Market.UniqueName]", f"'Customers'[Market] <> {TEST}"),
        "destination": _where("'Hotels'[Country]", "'Hotels'[Country.UniqueName]",
                              "'Hotels'[Country] = @F_DESTINATION"),
    },
    LOCKS: {
        "date": "'Calendar'[Date]",
        "real": _where("'Customers'[Market]", "'Customers'[Market.UniqueName]", f"'Customers'[Market] <> {TEST}"),
        "destination": _where("'Hotels'[Country]", "'Hotels'[Country.UniqueName]",
                              "'Hotels'[Country] = @F_DESTINATION"),
        "supplier": _where("'Suppliers'[Supplier Code]", "'Suppliers'[Supplier Code.UniqueName]",
                           "'Suppliers'[Supplier Code] = @F_SUPPLIER"),
    },
    REQUESTS: {
        "date": "'Calendario'[Fecha]",
        "real": _where("'Cliente'[Market]", "'Cliente'[Market.UniqueName]", f"'Cliente'[Market] <> {TEST}"),
        "client": _where("'Cliente'[Customer Code]", "'Cliente'[Customer Code.Key0]",
                         "'Cliente'[Customer Code] = @F_CLIENT"),
        "market": _where("'Cliente'[Country]", "'Cliente'[Country.UniqueName]", "'Cliente'[Country] = @F_MARKET"),
    },
    SEARCHES: {
        "date": "'Request Date'[Request Date]",
        "real": _where("'Customers'[Market]", "'Customers'[Market.UniqueName]", f"'Customers'[Market] <> {TEST}"),
        "client": _where("'Customers'[Customer Code]", "'Customers'[Customer Code.Key0]",
                         "'Customers'[Customer Code] = @F_CLIENT"),
        "market": _where("'Customers'[Country]", "'Customers'[Country.UniqueName]", "'Customers'[Country] = @F_MARKET"),
    },
}


def filters(cube: str, scope: str) -> str:
    """The period, no test agencies, and the dashboard's client, market, destination or supplier."""
    s = _SCOPES[cube]
    parts = [_within(s["date"]), s["real"]] + ([s[scope]] if scope != "all" else [])
    return ", ".join(parts)


def total(cube: str, scope: str, name: str, measure: str) -> str:
    return f'EVALUATE SUMMARIZECOLUMNS({filters(cube, scope)}, "{name}", {measure})'


def by(cube: str, scope: str, columns: list[str], measures: dict[str, str], top: int = 0, order: str = "",
       extra: tuple[str, ...] = ()) -> str:
    """SUMMARIZECOLUMNS by some columns (with their key columns), optionally the top N by the first measure.
    extra: more filters."""
    names = list(measures)
    inner = (f"SUMMARIZECOLUMNS({', '.join(columns)}, {', '.join([filters(cube, scope), *extra])}, "
             + ", ".join(f'"{n}", {m}' for n, m in measures.items()) + ")")
    if top:
        return f"EVALUATE TOPN({top}, {inner}, [{names[0]}], DESC) ORDER BY [{names[0]}] DESC"
    return f"EVALUATE {inner}" + (f" ORDER BY {order}" if order else f" ORDER BY [{names[0]}] DESC")


def count_of(cube: str, scope: str, name: str, columns: list[str], measure: str) -> str:
    """How many of something had activity (e.g. clients with bookings) in the period."""
    inner = f"SUMMARIZECOLUMNS({', '.join(columns)}, {filters(cube, scope)}, \"n\", {measure})"
    return f'EVALUATE ROW("{name}", COUNTROWS({inner}))'


# group-by columns with the key columns they need
CLIENT_NAME = ["'Customers'[Cliente]", "'Customers'[Cliente.Key0]"]
CLIENT_COUNTRY = ["'Customers'[Customer Country]", "'Customers'[Customer Country.UniqueName]"]
CLIENT_CODE = ["'Customers'[Code]", "'Customers'[Code.Key0]"]
NATIONALITY = ["'Countries'[Country]", "'Countries'[Country.UniqueName]"]  # the guests' (Bookings, Hotel Sales)
SUPPLIER = ["'Suppliers'[Supplier]", "'Suppliers'[Supplier.UniqueName]"]
HOTEL = ["'Unique Product'[Product Name]", "'Unique Product'[Product Name.UniqueName]"]
CHANNEL = ["'Sale Channel'[Sale Channel]", "'Sale Channel'[Sale Channel.UniqueName]"]
CANCELLED = ["'Canceled'[Canceled]", "'Canceled'[Canceled.UniqueName]"]
LEAD_TIME = ["'Lead Time'[Lead Time Description]"]
CONNECTION = ["'Product Type'[Module]", "'Product Type'[Module.UniqueName]"]
CONNECTION_CODE = ["'Product Type'[Module Code]", "'Product Type'[Module Code.UniqueName]"]
# bought from a supplier connection (not the company's own contracted hotels or generic bookings)
EXTERNAL = _where("'Product Type'[External]", "'Product Type'[External.UniqueName]",
                  "'Product Type'[External] = \"Yes\"")
# in Hotel Sales
HOTEL_COUNTRY = ["'Hotels'[Hotel Country]", "'Hotels'[Hotel Country.UniqueName]"]
HOTEL_CITY = ["'Hotels'[Hotel City]", "'Hotels'[Hotel City.UniqueName]"]
HS_CLIENT = ["'Customers'[Customer]", "'Customers'[Customer.UniqueName]"]
HS_CLIENT_CODE = ["'Customers'[Id Cli]", "'Customers'[Id Cli.UniqueName]"]
HS_CLIENT_COUNTRY = ["'Customers'[Default Country]", "'Customers'[Default Country.UniqueName]"]
HS_HOTEL = ["'Hotels'[Hotel]", "'Hotels'[Hotel.UniqueName]"]
HS_MODULE = ["'Modules'[Module]", "'Modules'[Module.UniqueName]"]
HS_WINDOW = ["'Booking Window Interval'[Booking Window Interval]",
             "'Booking Window Interval'[Booking Window Interval.UniqueName]"]
HS_CHANNEL = ["'Interfaces'[Interface]", "'Interfaces'[Interface.UniqueName]"]
KNOWN_PLACE = _where("'Hotels'[Hotel Country]", "'Hotels'[Hotel Country.UniqueName]",
                     "NOT 'Hotels'[Hotel Country] IN {\"N/A\", \"Unknown\"}")
KNOWN_CITY = _where("'Hotels'[Hotel City]", "'Hotels'[Hotel City.UniqueName]",
                    "NOT 'Hotels'[Hotel City] IN {\"N/A\", \"Unknown\"}")
OUTCOME = ["'Tipo Fallos'[Fallo]", "'Tipo Fallos'[Fallo.UniqueName]"]
LOCK_TYPE = ["'Lock Types'[Lock Type]", "'Lock Types'[Lock Type.UniqueName]"]


# ---------------------------------------------------------------- formats --

def amount(column: str) -> dict:
    return {"column": column, "d3_format": "~s", "prefix": "AED ", "suffix": ""}


def count(column: str) -> dict:
    return {"column": column, "d3_format": ",.0f", "prefix": "", "suffix": ""}


def compact(column: str) -> dict:
    """Big counts written short: 1.3B, 660k."""
    return {"column": column, "d3_format": "~s", "prefix": "", "suffix": ""}


def percent(column: str) -> dict:
    return {"column": column, "d3_format": ".1%", "prefix": "", "suffix": ""}


def decimals(column: str, places: int = 2, suffix: str = "") -> dict:
    return {"column": column, "d3_format": f",.{places}f", "prefix": "", "suffix": suffix}


# ---------------------------------------------------------------- charts --

def chart(cid: str, title: str, about: str, kind: str, steps: list[tuple[str, str, str]], combine: str = "",
          x: str = "", y: list[str] | None = None, color: str = "", formats: list[dict] | None = None,
          width: str = "half", compare: bool = True, **style) -> dict:
    """One dashboard chart. steps: (name, cube, query); combine: DuckDB SQL over the steps. compare=False: never
    next to the comparison period (a table whose own numbers are the point)."""
    plan = Plan([Step(name, cube, query) for name, cube, query in steps], combine)
    cubes_used = plan.cubes
    return {
        "id": cid, "builtin": True, "cube": cubes_used[0] if len(cubes_used) == 1 else "",
        "title": title, "question": about, "query": plan.text(), "plan": plan.to_dict(),
        "date_column": _SCOPES[cubes_used[0]]["date"] if len(cubes_used) == 1 else "auto",
        "chart_type": kind, "x": x, "y": list(y or []), "color": color,
        "style": {"formats": list(formats or []), **style}, "width": width, "period_mode": "dashboard",
        **({} if compare else {"compare": False}),
    }


def kpi(cid: str, title: str, about: str, cube: str, scope: str, measure: str, fmt, **style) -> dict:
    return chart(cid, title, about, "kpi", [("result", cube, total(cube, scope, title, measure))],
                 formats=[fmt(title)], **style)


def headline_numbers(prefix: str, scope: str, who: str) -> list[dict]:
    """The eight numbers at the top: money, volume, reach, demand and its conversion."""
    p = prefix
    clients = [] if scope == "client" else [
        chart(f"{p}-clients", "Active clients", f"Clients{who} with at least one booking in the period.", "kpi",
              [("result", BOOKINGS, count_of(BOOKINGS, scope, "Active clients", CLIENT_CODE, "[Reservations Count]"))],
              formats=[count("Active clients")])]
    avg = [kpi(f"{p}-avg", "Average booking value", f"Sales per booking{who} (cancelled lines included).",
               BOOKINGS, scope, "[Avg Sale]", amount)] if scope == "client" else []
    return [
        kpi(f"{p}-sales", "Sales", f"Sales{who} in AED, net of cancellations (cancelled lines keep their fees).",
            BOOKINGS, scope, "[Sale]", amount),
        kpi(f"{p}-profit", "Profit", f"Sales minus supplier cost{who}, in AED.", BOOKINGS, scope, "[Profit]", amount),
        kpi(f"{p}-margin", "Margin", f"Profit as a share of sales{who}.", BOOKINGS, scope, "[Markup]", percent),
        kpi(f"{p}-bookings", "Bookings", f"Booking lines made{who} in the period, cancelled ones included.",
            BOOKINGS, scope, "[Reservations Count]", count),
        kpi(f"{p}-roomnights", "Room nights", f"Rooms x nights booked{who}.", BOOKINGS, scope, "[Room Nights]", count),
        *clients, *avg,
        kpi(f"{p}-searches", "Searches", f"Hotel searches (availability requests){who} received through the API.",
            SEARCHES, scope, "[Total Requests]", compact),
        kpi(f"{p}-l2b", "Look-to-book", f"API availability requests per booking{who}: lower means traffic that "
            "converts better (and costs less to serve).", REQUESTS, scope, "[L2B]", compact, lower_is_better=True),
    ]


def trend(cid: str, title: str, about: str, cube: str, scope: str, name: str, measure: str, fmt,
          kind: str = "line", width: str = "full") -> dict:
    date = _SCOPES[cube]["date"]
    query = by(cube, scope, [date], {name: measure}, order=date)
    day = date.split("[")[1].rstrip("]")
    return chart(cid, title, about, kind, [("result", cube, query)], x=day, y=[name], formats=[fmt(name)],
                 width=width)


def ranking(cid: str, title: str, about: str, scope: str, columns: list[str], label: str, name: str,
            measure: str, fmt, top: int = 10, cube: str = BOOKINGS, extra: tuple[str, ...] = ()) -> dict:
    query = by(cube, scope, columns, {name: measure}, top=top, extra=extra)
    return chart(cid, title, about, "horizontal_bar", [("result", cube, query)], x=label, y=[name],
                 formats=[fmt(name)], sort="value_desc")


def relabelled(cube: str, scope: str, columns: list[str], label: str, expression: str,
               measures: dict[str, str]) -> str:
    """By some columns, shown under a label worked out from them (e.g. "XML" for "XML - GTE - ...")."""
    inner = by(cube, scope, columns, measures).removeprefix("EVALUATE ").split(" ORDER BY ")[0]
    return (f'EVALUATE SELECTCOLUMNS({inner}, "{label}", {expression}, '
            + ", ".join(f'"{n}", [{n}]' for n in measures) + f") ORDER BY [{list(measures)[0]}] DESC")


def channel_share(cid: str, scope: str, who: str) -> dict:
    name = "'Sale Channel'[Sale Channel]"
    query = relabelled(BOOKINGS, scope, CHANNEL, "Channel",
                       f'LEFT({name}, SEARCH(" - ", {name}, 1, LEN({name}) + 1) - 1)', {"Sales": "[Sale]"})
    return chart(cid, "Sales by channel", f"How{who} sales are made: XML (API), B2B web portal or B2C.", "donut",
                 [("result", BOOKINGS, query)], x="Channel", y=["Sales"], formats=[amount("Sales")])


def confirmed_and_cancelled(cid: str, scope: str, who: str) -> dict:
    flag = "'Canceled'[Canceled]"
    query = relabelled(BOOKINGS, scope, CANCELLED, "Status",
                       f'SWITCH({flag}, "Yes", "Cancelled", "No", "Confirmed", {flag})',
                       {"Bookings": "[Reservations Count]"})
    return chart(cid, "Confirmed and cancelled", f"Booking lines{who} made in the period that stayed confirmed, "
                 "and those since cancelled.", "donut", [("result", BOOKINGS, query)], x="Status", y=["Bookings"],
                 formats=[count("Bookings")])


def booking_window(cid: str, scope: str, who: str) -> dict:
    query = by(BOOKINGS, scope, LEAD_TIME, {"Bookings": "[Reservations Count]"})
    return chart(cid, "Booking window", f"How far ahead of check-in{who} bookings are made (lead time).", "donut",
                 [("result", BOOKINGS, query)], x="Lead Time Description", y=["Bookings"], formats=[count("Bookings")])


HOTELS_ONLY = _where("'Product Type'[Product Type]", "'Product Type'[Product Type.UniqueName]",
                     "'Product Type'[Product Type] = \"Accommodation\"")


def top_hotels(cid: str, scope: str, who: str, width: str = "full") -> dict:
    grouped = (f"SUMMARIZECOLUMNS({', '.join(HOTEL)}, {filters(BOOKINGS, scope)}, {HOTELS_ONLY}, "
               '"Bookings", [Reservations Count], "Room nights", [Room Nights], "Sales", [Sale])')
    query = (f"EVALUATE TOPN(10, FILTER({grouped}, 'Unique Product'[Product Name] <> \"N/A\"), "
             "[Bookings], DESC, [Sales], DESC) ORDER BY [Bookings] DESC, [Sales] DESC")
    return chart(cid, "Top 10 hotels", f"The hotels{who} booked most in the period.", "table",
                 [("result", BOOKINGS, query)], x="Product Name", y=["Bookings", "Room nights", "Sales"],
                 formats=[count("Bookings"), count("Room nights"), amount("Sales")], width=width)


def destinations(cid: str, scope: str, who: str, title: str = "Top 10 destinations") -> dict:
    """Where the guests stay: hotel sales by the hotel's country (Hotel Sales cube)."""
    return ranking(cid, title, f"Where the guests{who} stay: hotel sales by the hotel's country; "
                   "grey: the comparison period.", scope, HOTEL_COUNTRY, "Hotel Country", "Sales", "[Total Sales]",
                   amount, cube=HOTEL_SALES, extra=(KNOWN_PLACE,))


def nationalities(cid: str, scope: str, who: str, cube: str = BOOKINGS, title: str = "Top 10 guest nationalities"
                  ) -> dict:
    measure = "[Sale]" if cube == BOOKINGS else "[Total Sales]"
    return ranking(cid, title, f"The guests'{who} nationality, as the agency sent it with "
                   "the booking; grey: the comparison period. (An agency that sends one value for every booking "
                   "counts all of it there.)", scope, NATIONALITY, "Country", "Sales", measure, amount, cube=cube)


def searches_and_bookings(cid: str, scope: str, who: str) -> dict:
    """Top clients by searches next to their bookings and sales: who asks a lot and who buys."""
    searches = by(SEARCHES, scope, ["'Customers'[Customer Code]", "'Customers'[Customer Code.Key0]",
                                    "'Customers'[Customer]", "'Customers'[Customer.UniqueName]"],
                  {"Searches": "[Total Requests]"}, top=15)
    bookings = by(BOOKINGS, scope, CLIENT_CODE, {"Bookings": "[Reservations Count]", "Sales": "[Sale]"})
    combine = ('SELECT s."Customer" AS "Client", s."Searches", COALESCE(b."Bookings", 0) AS "Bookings", '
               'COALESCE(b."Sales", 0) AS "Sales", '
               'CASE WHEN COALESCE(b."Bookings", 0) > 0 THEN s."Searches" / b."Bookings" END AS "Searches per booking" '
               'FROM searches s LEFT JOIN bookings b ON upper(trim(CAST(s."Customer Code" AS VARCHAR))) = '
               'upper(trim(CAST(b."Code" AS VARCHAR))) ORDER BY s."Searches" DESC')
    return chart(cid, "Top clients: searches, bookings and look-to-book",
                 f"The clients{who} that search most, with what they booked: a high number of searches per "
                 "booking is traffic that hardly converts.", "table",
                 [("searches", SEARCHES, searches), ("bookings", BOOKINGS, bookings)], combine,
                 x="Client", y=["Searches", "Bookings", "Sales", "Searches per booking"],
                 formats=[compact("Searches"), count("Bookings"), amount("Sales"), compact("Searches per booking")],
                 width="full")


# ---------------------------------------------------------------- the dashboards --

def overview() -> dict:
    s, who = "all", ""
    charts = headline_numbers("ov", s, who) + [
        trend("ov-sales-trend", "Sales", "Sales by day (by week or month for longer periods), next to the "
              "comparison period.", BOOKINGS, s, "Sales", "[Sale]", amount),
        trend("ov-profit-trend", "Profit", "Profit by day, next to the comparison period.", BOOKINGS, s, "Profit",
              "[Profit]", amount, width="half"),
        trend("ov-bookings-trend", "Bookings", "Booking lines by day, next to the comparison period.", BOOKINGS, s,
              "Bookings", "[Reservations Count]", count, kind="bar", width="half"),
        ranking("ov-top-markets", "Top 10 client countries", "Where the agencies that buy are based (the market); "
                "grey: the comparison period.", s, CLIENT_COUNTRY, "Customer Country", "Sales", "[Sale]", amount),
        ranking("ov-top-clients", "Top 10 clients", "The clients with the most sales; grey: the comparison period.",
                s, CLIENT_NAME, "Cliente", "Sales", "[Sale]", amount),
        nationalities("ov-nationalities", s, who),
        channel_share("ov-channel", s, who),
        chart("ov-destinations-map", "Hotel sales by destination", "Where the guests stay: hotel sales by the "
              "hotel's country.", "map",
              [("result", HOTEL_SALES, by(HOTEL_SALES, s, HOTEL_COUNTRY, {"Sales": "[Total Sales]"},
                                          extra=(KNOWN_PLACE,)))],
              x="Hotel Country", y=["Sales"], formats=[amount("Sales")]),
        destinations("ov-top-destinations", s, who),
        chart("ov-top-suppliers", "Top 10 suppliers", "The suppliers behind the most sales, with the profit and "
              "margin they leave.", "table",
              [("result", BOOKINGS, by(BOOKINGS, s, SUPPLIER, {"Sales": "[Sale]", "Profit": "[Profit]",
                                                                "Margin": "[Markup]"}, top=10))],
              x="Supplier", y=["Sales", "Profit", "Margin"],
              formats=[amount("Sales"), amount("Profit"), percent("Margin")], width="full"),
        booking_window("ov-lead-time", s, who),
        confirmed_and_cancelled("ov-cancelled", s, who),
        trend("ov-searches-trend", "Searches", "Hotel searches received through the API, by day.", SEARCHES, s,
              "Searches", "[Total Requests]", compact, width="half"),
        trend("ov-l2b-trend", "Look-to-book", "API availability requests per booking, by day: lower is better.",
              REQUESTS, s, "Look-to-book", "[L2B]", compact, width="half"),
        searches_and_bookings("ov-searches-clients", s, who),
    ]
    return {"id": "overview", "name": "Business overview", "builtin": VERSION, "filters": [], "charts": charts}


def client() -> dict:
    s, who = "client", " of this client"
    charts = headline_numbers("cl", s, who) + [
        trend("cl-sales-trend", "Sales", "The client's sales by day, next to the comparison period.", BOOKINGS, s,
              "Sales", "[Sale]", amount),
        trend("cl-bookings-trend", "Bookings", "The client's booking lines by day.", BOOKINGS, s, "Bookings",
              "[Reservations Count]", count, kind="bar", width="half"),
        trend("cl-requests-trend", "API requests", "Requests the client sent to the API by day (all request types).",
              REQUESTS, s, "API requests", "[Requests]", compact, width="half"),
        destinations("cl-destinations", s, who),
        nationalities("cl-nationalities", s, who),
        ranking("cl-suppliers", "Suppliers used", "The suppliers that served the client's bookings, by sales.", s,
                SUPPLIER, "Supplier", "Sales", "[Sale]", amount),
        top_hotels("cl-hotels", s, who, width="half"),
        confirmed_and_cancelled("cl-cancelled", s, who),
        booking_window("cl-lead-time", s, who),
        chart("cl-outcomes", "API request outcomes", "How the client's API requests were answered: correct, no "
              "results or an error.", "donut",
              [("result", REQUESTS, by(REQUESTS, s, OUTCOME, {"Requests": "[Requests]"}, top=6))],
              x="Fallo", y=["Requests"], formats=[count("Requests")]),
        trend("cl-response-time", "API response time", "Average seconds the API took to answer the client, by day.",
              REQUESTS, s, "Seconds", "[AVG Response Time Sec]", lambda c: decimals(c, 2, " s"), width="half"),
    ]
    return {"id": "client", "name": "Client view", "builtin": VERSION, "charts": charts, "filters": [{
        "key": "client", "label": "Client", "placeholder": "@F_CLIENT",
        "options": {"cube": BOOKINGS, "value": "Code", "label": "{Cliente} - {Code}",
                    "query": by(BOOKINGS, "all", CLIENT_CODE + CLIENT_NAME, {"Sales": "[Sale]"}, top=2000)},
    }]}


def market() -> dict:
    s, who = "market", " from this market"
    charts = headline_numbers("mk", s, who) + [
        trend("mk-sales-trend", "Sales", "The market's sales by day, next to the comparison period.", BOOKINGS, s,
              "Sales", "[Sale]", amount),
        ranking("mk-top-clients", "Top 10 clients", "The clients driving the market; grey: the comparison period, "
                "so growing and shrinking clients stand out.", s, CLIENT_NAME, "Cliente", "Sales", "[Sale]", amount),
        nationalities("mk-nationalities", s, who, title="Who travels: guest nationalities"),
        destinations("mk-destinations", s, who, title="Where they go: top 10 destinations"),
        top_hotels("mk-hotels", s, who, width="half"),
        searches_and_bookings("mk-searches-clients", s, who),
        trend("mk-searches-trend", "Searches", "The market's hotel searches by day.", SEARCHES, s, "Searches",
              "[Total Requests]", compact, width="half"),
        channel_share("mk-channel", s, who),
        booking_window("mk-lead-time", s, who),
        confirmed_and_cancelled("mk-cancelled", s, who),
    ]
    return {"id": "market", "name": "Market view", "builtin": VERSION, "charts": charts, "filters": [{
        "key": "market", "label": "Market (client country)", "placeholder": "@F_MARKET",
        "options": {"cube": BOOKINGS, "value": "Customer Country", "label": "{Customer Country}", "title_case": True,
                    "query": by(BOOKINGS, "all", CLIENT_COUNTRY, {"Sales": "[Sale]"})},
    }]}


def supplier() -> dict:
    """One supplier connection: what it sells for us, what we ask of it, and how reliably it answers."""
    s, who = "supplier", " through this supplier"
    charts = [
        kpi("su-sales", "Sales", f"Sales of bookings made{who}, in AED.", BOOKINGS, s, "[Sale]", amount),
        kpi("su-profit", "Profit", f"Profit left by bookings made{who}, in AED.", BOOKINGS, s, "[Profit]", amount),
        kpi("su-margin", "Margin", f"Profit as a share of sales{who}.", BOOKINGS, s, "[Markup]", percent),
        kpi("su-bookings", "Bookings", f"Booking lines made{who}, cancelled ones included.", BOOKINGS, s,
            "[Reservations Count]", count),
        kpi("su-requests", "Supplier requests", "Requests the booking engine sent to this supplier (availability, "
            "cancellation policy, booking...).", SUPPLIER_REQUESTS, s, "[Requests]", compact),
        kpi("su-l2b", "Look-to-book", "Requests sent to this supplier per booking made with it: lower is cheaper "
            "traffic.", SUPPLIER_REQUESTS, s, "[L2B]", compact, lower_is_better=True),
        kpi("su-response", "Response time", "How long the supplier took to answer, on average.", SUPPLIER_REQUESTS,
            s, "[AVG Response Time Sec]", lambda c: decimals(c, 2, " s"), lower_is_better=True),
        kpi("su-locks", "Hotel locks", "Hotel options from this supplier that failed in the booking flow (no "
            "results, a changed price or an error when rechecked): lost bookings.", LOCKS, s, "[Locks Number]",
            count, lower_is_better=True),
        trend("su-sales-trend", "Sales", "Sales of the supplier's bookings by day, next to the comparison period.",
              BOOKINGS, s, "Sales", "[Sale]", amount),
        trend("su-requests-trend", "Supplier requests", "Requests sent to the supplier by day.", SUPPLIER_REQUESTS,
              s, "Requests", "[Requests]", compact, width="half"),
        trend("su-response-trend", "Response time", "The supplier's average response time by day.",
              SUPPLIER_REQUESTS, s, "Seconds", "[AVG Response Time Sec]", lambda c: decimals(c, 2, " s"),
              width="half"),
        chart("su-outcomes", "Request outcomes", "How the supplier answered: correct, no results, time-outs or "
              "errors.", "donut",
              [("result", SUPPLIER_REQUESTS, by(SUPPLIER_REQUESTS, s, OUTCOME, {"Requests": "[Requests]"}, top=6))],
              x="Fallo", y=["Requests"], formats=[compact("Requests")]),
        chart("su-lock-reasons", "Hotel locks by reason", "Why the supplier's hotel options failed when rechecked "
              "in the booking flow.", "donut",
              [("result", LOCKS, by(LOCKS, s, LOCK_TYPE, {"Locks": "[Locks Number]"}))],
              x="Lock Type", y=["Locks"], formats=[count("Locks")]),
        ranking("su-clients", "Top 10 clients", "The clients who booked most through this supplier; grey: the "
                "comparison period.", s, CLIENT_NAME, "Cliente", "Sales", "[Sale]", amount),
        destinations("su-destinations", s, who),
        ranking("su-request-clients", "Clients behind the most requests", "Whose searches made the engine ask "
                "this supplier most (the cost side of the traffic).", s, ["'Cliente'[Cliente]",
                "'Cliente'[Cliente.Key0]"], "Cliente", "Requests", "[Requests]", compact, cube=SUPPLIER_REQUESTS),
        ranking("su-lock-countries", "Hotel locks by destination", "Where the supplier's hotel options fail most "
                "often.", s, ["'Hotels'[Country]", "'Hotels'[Country.UniqueName]"], "Country", "Locks",
                "[Locks Number]", count, cube=LOCKS),
        top_hotels("su-hotels", s, who),
        confirmed_and_cancelled("su-cancelled", s, who),
        booking_window("su-lead-time", s, who),
    ]
    return {"id": "supplier", "name": "Supplier view", "builtin": VERSION, "charts": charts, "filters": [{
        "key": "supplier", "label": "Supplier connection", "placeholder": "@F_SUPPLIER",
        "options": {"cube": BOOKINGS, "value": "Module Code", "label": "{Module} - {Module Code}",
                    "query": by(BOOKINGS, "all", CONNECTION_CODE + CONNECTION, {"Sales": "[Sale]"},
                                extra=(EXTERNAL,))},
    }]}


def destination() -> dict:
    """One destination country - where the hotel is: who sends guests there, what they book, and how well it
    is supplied. Hotel bookings (the Hotel Sales cube): the destination of other services isn't in the cubes."""
    s, who = "destination", " for this destination"
    hs = HOTEL_SALES
    charts = [
        kpi("de-sales", "Sales", f"Hotel sales{who} (hotels in this country), in AED.", hs, s, "[Total Sales]", amount),
        kpi("de-profit", "Profit", f"Hotel profit{who}, in AED.", hs, s, "[Total Profit]", amount),
        kpi("de-margin", "Margin", f"Profit as a share of sales{who}.", hs, s, "[Markup]", percent),
        kpi("de-bookings", "Bookings", f"Hotel bookings{who}, cancelled ones included.", hs, s, "[Bookings]", count),
        kpi("de-roomnights", "Room nights", f"Rooms x nights booked{who}.", hs, s, "[Total Room Nights]", count),
        chart("de-clients", "Active clients", f"Clients with at least one hotel booking{who}.", "kpi",
              [("result", hs, count_of(hs, s, "Active clients", HS_CLIENT_CODE, "[Bookings]"))],
              formats=[count("Active clients")]),
        kpi("de-hotel-requests", "Hotel requests", "Hotels in this country asked for in client searches (a search "
            "for 20 hotels counts 20).", HOTEL_REQUESTS, s, "[Total Hotel Requests]", compact),
        kpi("de-availability", "Availability", "The share of those hotel requests answered with availability: how "
            "well the destination is supplied.", HOTEL_REQUESTS, s, "[% Hotel Requests OK]", percent),
        trend("de-sales-trend", "Sales", "Hotel sales for the destination by day, next to the comparison period.",
              hs, s, "Sales", "[Total Sales]", amount),
        ranking("de-cities", "Top 10 cities", "The cities where the guests stay; grey: the comparison period.", s,
                HOTEL_CITY, "Hotel City", "Sales", "[Total Sales]", amount, cube=hs, extra=(KNOWN_CITY,)),
        nationalities("de-nationalities", s, who, cube=hs, title="Who travels here: guest nationalities"),
        ranking("de-markets", "Booked from: agency countries", "Where the agencies selling this destination are based; "
                "grey: the comparison period.", s, HS_CLIENT_COUNTRY, "Default Country", "Sales", "[Total Sales]",
                amount, cube=hs),
        ranking("de-top-clients", "Top 10 clients", "The clients selling the destination most; grey: the comparison "
                "period.", s, HS_CLIENT, "Customer", "Sales", "[Total Sales]", amount, cube=hs),
        hs_top_hotels("de-hotels", s, who),
        ranking("de-suppliers", "Top 10 supplier connections", "The connections the destination's hotel bookings "
                "came through, by sales.", s, HS_MODULE, "Module", "Sales", "[Total Sales]", amount, cube=hs),
        trend("de-requests-trend", "Hotel requests", "Hotels in this country asked for in client searches, by day.",
              HOTEL_REQUESTS, s, "Hotel requests", "[Total Hotel Requests]", compact, width="half"),
        chart("de-lock-reasons", "Hotel locks by reason", "Hotel options in this country that failed when rechecked "
              "in the booking flow, by reason.", "donut",
              [("result", LOCKS, by(LOCKS, s, LOCK_TYPE, {"Locks": "[Locks Number]"}))],
              x="Lock Type", y=["Locks"], formats=[count("Locks")]),
        chart("de-lead-time", "Booking window", f"How many days ahead of arrival the hotel bookings{who} are made.",
              "donut", [("result", hs, by(hs, s, HS_WINDOW, {"Bookings": "[Bookings]"}))],
              x="Booking Window Interval", y=["Bookings"], formats=[count("Bookings")]),
        chart("de-cancelled", "Confirmed and cancelled", f"Hotel bookings{who} made in the period that stayed "
              "confirmed, and those since cancelled.", "donut",
              [("result", hs, relabelled(hs, s, CANCELLED, "Status", 'SWITCH(\'Canceled\'[Canceled], "Yes", '
                                         '"Cancelled", "No", "Confirmed", \'Canceled\'[Canceled])',
                                         {"Bookings": "[Bookings]"}))],
              x="Status", y=["Bookings"], formats=[count("Bookings")]),
        chart("de-channel", "Sales by channel", f"How the hotel bookings{who} are sold: XML (API), web or other.",
              "donut", [("result", hs, by(hs, s, HS_CHANNEL, {"Sales": "[Total Sales]"}))],
              x="Interface", y=["Sales"], formats=[amount("Sales")]),
    ]
    return {"id": "destination", "name": "Destination view", "builtin": VERSION, "charts": charts, "filters": [{
        "key": "destination", "label": "Destination (hotel country)", "placeholder": "@F_DESTINATION",
        "options": {"cube": hs, "value": "Hotel Country", "label": "{Hotel Country}",
                    "query": by(hs, "all", HOTEL_COUNTRY, {"Sales": "[Total Sales]"}, extra=(KNOWN_PLACE,))},
    }]}


def hs_top_hotels(cid: str, scope: str, who: str) -> dict:
    grouped = (f"SUMMARIZECOLUMNS({', '.join(HS_HOTEL)}, {filters(HOTEL_SALES, scope)}, "
               '"Bookings", [Bookings], "Room nights", [Total Room Nights], "Sales", [Total Sales])')
    query = (f"EVALUATE TOPN(10, FILTER({grouped}, NOT 'Hotels'[Hotel] IN {{\"N/A\", \"Unknown\", \"nan\"}}), "
             "[Bookings], DESC, [Sales], DESC) ORDER BY [Bookings] DESC, [Sales] DESC")
    return chart(cid, "Top 10 hotels", f"The hotels{who} booked most in the period.", "table",
                 [("result", HOTEL_SALES, query)], x="Hotel", y=["Bookings", "Room nights", "Sales"],
                 formats=[count("Bookings"), count("Room nights"), amount("Sales")], width="full")


def all_dashboards() -> list[dict]:
    """In the order they are listed (the first opens the app): the whole business, then by market,
    destination, client and supplier."""
    return [overview(), market(), destination(), client(), supplier()]
