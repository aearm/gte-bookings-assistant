"""The bulk reader for cube results (adomd_bulk/AdomdBulk.dll + ssas.decode_bulk): it must give exactly
the rows the old row-by-row reader (pyadomd) gives, and fall back to that reader when it can't.

- Decoder tests run everywhere (no server, no .NET).
- .NET tests feed the compiled reader in-memory tables (System.Data) and compare it with pyadomd's own
  row reader on the same data; they run on Windows with pythonnet and ADOMD.NET, no server needed.
- The live test compares both readers on the real server (RUN_LIVE=1)."""
import json
import math
import os
import random
import struct
import sys
import time
import types
from contextlib import nullcontext
from datetime import datetime

import pandas as pd
import pytest

import config
import ssas


def payload(columns, types_, data, complete=True, fmt=ssas.BULK_FORMAT, rows=None):
    """What the bulk reader writes, built by hand."""
    count = rows if rows is not None else (len(data[0]) if data else 0)
    return json.dumps({"format": fmt, "complete": complete, "rows": count, "columns": columns,
                       "types": types_, "data": data})


# ---------------------------------------------------------------- decoding (no .NET) --

def test_columns_become_row_tuples_with_python_values():
    text = payload(["Calendar[Year]", "Calendar[Date]", "Customers[Code]", "[Sale]", "[Flag]"],
                   ["System.Int64", "System.DateTime", "System.String", "System.Object", "System.Boolean"],
                   [[2025, 2026], ["2025-01-02T03:04:05", None], ["A1", None], [10.5, 3], [True, None]])
    rows, complete = ssas.decode_bulk(text)
    assert complete
    assert rows == [(2025, datetime(2025, 1, 2, 3, 4, 5), "A1", 10.5, True),
                    (2026, None, None, 3, None)]
    assert type(rows[1][3]) is int and type(rows[0][3]) is float  # 3 stays a whole number, 10.5 a float


def test_text_with_tabs_quotes_newlines_and_unicode_comes_back_unchanged():
    values = ['tab\there', 'say "hi" \'x\'', 'back \\ slash', 'l1\nl2\r\n', 'nul\x00 \x01\x1f',
              'café 中 م', 'emoji \U0001F600', '  ', '  leading', 'nan', '']
    # The reader escapes surrogates one by one (😀); json joins them into one character again
    text = payload(["[t]"], ["System.Object"], [values])
    text = text.replace("\U0001F600", "\\ud83d\\ude00")
    rows, _ = ssas.decode_bulk(text)
    assert [r[0] for r in rows] == values


def test_a_broken_half_character_survives():
    rows, _ = ssas.decode_bulk('{"format":1,"complete":true,"rows":1,"columns":["c"],'
                               '"types":["System.String"],"data":[["a\\ud83d"]]}')
    assert rows == [("a\ud83d",)]


def test_special_numbers_round_trip_exactly():
    text = ('{"format":1,"complete":true,"rows":7,"columns":["x"],"types":["System.Double"],'
            '"data":[[NaN,Infinity,-Infinity,-0.0,0.10000000000000001,1.0000000000000000E+21,'
            '9223372036854775807.0]]}')
    rows, _ = ssas.decode_bulk(text)
    values = [r[0] for r in rows]
    assert math.isnan(values[0]) and values[1] == math.inf and values[2] == -math.inf
    assert str(values[3]) == "-0.0" and values[4] == 0.1 and values[5] == 1e21
    assert all(type(v) is float for v in values)


def test_big_whole_numbers_stay_exact():
    rows, _ = ssas.decode_bulk(payload(["n"], ["System.UInt64"], [[18446744073709551615, -9223372036854775808]]))
    assert rows == [(18446744073709551615,), (-9223372036854775808,)]


def test_empty_cells_are_none_in_every_kind_of_column():
    kinds = ["System.String", "System.Int64", "System.Double", "System.Decimal", "System.DateTime",
             "System.Boolean", "System.Guid", "System.Object"]
    rows, _ = ssas.decode_bulk(payload([f"c{i}" for i in range(len(kinds))], kinds, [[None]] * len(kinds)))
    assert rows == [(None,) * len(kinds)]


def test_dates_keep_whole_seconds_and_early_years():
    rows, _ = ssas.decode_bulk(payload(["d"], ["System.DateTime"], [["0001-01-01T00:00:00", "9999-12-31T23:59:59"]]))
    assert rows == [(datetime(1, 1, 1),), (datetime(9999, 12, 31, 23, 59, 59),)]


def test_max_rows_cuts_the_result():
    text = payload(["n"], ["System.Int64"], [[1, 2, 3, 4, 5]], complete=False)
    rows, complete = ssas.decode_bulk(text, max_rows=3)
    assert rows == [(1,), (2,), (3,)] and complete  # enough rows: nothing left to read
    assert ssas.decode_bulk(text, max_rows=10) == ([(1,), (2,), (3,), (4,), (5,)], False)


def test_an_empty_result_and_a_result_without_columns():
    assert ssas.decode_bulk(payload(["a", "b"], ["System.String", "System.Object"], [[], []])) == ([], True)
    assert ssas.decode_bulk(payload([], [], [], rows=2)) == ([(), ()], True)


@pytest.mark.parametrize("text", [
    "not json",
    "[1, 2]",
    payload(["n"], ["System.Int64"], [[1]], fmt=99),
    payload(["a", "b"], ["System.Int64"], [[1], [2]]),                    # a type missing
    payload(["n"], ["System.Int64"], [[1, 2]], rows=3),                   # row count is wrong
    payload(["d"], ["System.DateTime"], [["2 Jan 2026"]]),                # not an ISO date
    '{"format":1,"complete":true,"rows":1,"columns":["c"],"types":["System.String"]}',  # no data
])
def test_unreadable_text_is_reported_as_a_format_error(text):
    with pytest.raises(ssas.BulkFormatError):
        ssas.decode_bulk(text)


# ---------------------------------------------------------------- reading and falling back (no .NET) --

class FakeCursor:
    """Stands in for pyadomd's cursor: rows the row reader would still give, one by one."""

    def __init__(self, rest, columns=("a",)):
        self._reader = object()
        self.rest = list(rest)
        self.fetched = 0
        self.description = [types.SimpleNamespace(name=c) for c in columns]

    def fetchone(self):
        for row in self.rest:
            self.fetched += 1
            yield row

    def execute(self, query):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeBulk:
    def __init__(self, text):
        self.text, self.calls = text, []

    def Read(self, reader, max_rows):  # noqa: N802  (the .NET method's name)
        self.calls.append(max_rows)
        return self.text


def test_a_complete_bulk_read_never_reads_row_by_row():
    cur, bulk = FakeCursor([("x",)]), FakeBulk(payload(["a"], ["System.Int64"], [[1, 2]]))
    assert ssas._read_rows(cur, None, bulk) == [(1,), (2,)]
    assert cur.fetched == 0 and bulk.calls == [0]


def test_max_rows_is_handed_to_the_bulk_reader():
    bulk = FakeBulk(payload(["a"], ["System.Int64"], [[1, 2]]))
    ssas._read_rows(FakeCursor([]), 2, bulk)
    ssas._read_rows(FakeCursor([]), 10**12, bulk)
    assert bulk.calls == [2, 2**31 - 1]


def test_where_the_bulk_reader_stops_the_row_reader_takes_over(monkeypatch):
    monkeypatch.setattr(ssas, "_current_row", lambda cur: ("row 3",))
    cur = FakeCursor([("row 4",), ("row 5",), ("row 6",)])
    bulk = FakeBulk(payload(["a"], ["System.String"], [["row 1", "row 2"]], complete=False))
    assert ssas._read_rows(cur, None, bulk) == [("row 1",), ("row 2",), ("row 3",), ("row 4",), ("row 5",), ("row 6",)]
    cur = FakeCursor([("row 4",), ("row 5",), ("row 6",)])
    assert ssas._read_rows(cur, 4, bulk) == [("row 1",), ("row 2",), ("row 3",), ("row 4",)]
    cur = FakeCursor([("row 4",)])
    assert ssas._read_rows(cur, 3, bulk) == [("row 1",), ("row 2",), ("row 3",)] and cur.fetched == 0


def test_without_the_bulk_reader_rows_are_read_one_by_one():
    cur = FakeCursor([(1,), (2,), (3,)])
    assert ssas._read_rows(cur, 2, None) == [(1,), (2,)]
    assert ssas._read_rows(FakeCursor([(1,), (2,)]), None, None) == [(1,), (2,)]


class StreamingReader:
    """A reader with rows still coming from the server, and the command that started it."""

    def __init__(self, more=True, cancel_fails=False):
        self.more, self.cancel_fails, self.calls = more, cancel_fails, []

    def Read(self):  # noqa: N802
        self.calls.append("read")
        return self.more

    def Cancel(self):  # noqa: N802
        self.calls.append("cancel")
        if self.cancel_fails:
            raise RuntimeError("cancel failed")

    def Close(self):  # noqa: N802
        self.calls.append("close")


@pytest.mark.parametrize("more, cancel_fails, calls", [
    (True, False, ["read", "cancel", "close"]),   # rows left: the server is told to stop, then closed
    (False, False, ["read", "close"]),            # nothing left: just closed
    (True, True, ["read", "cancel"]),             # cancelling failed: pyadomd closes it as before
])
def test_rows_beyond_max_rows_are_not_waited_for(more, cancel_fails, calls):
    stream = StreamingReader(more, cancel_fails)
    cur = types.SimpleNamespace(_reader=stream, _cmd=stream)
    ssas._skip_the_rest(cur)
    assert stream.calls == calls


@pytest.mark.parametrize("value, on",[(None, True), ("1", True), ("0", False), ("off", False),
                                       (" False ", False), ("no", False), ("yes", True)])
def test_the_bulk_reader_can_be_switched_off(monkeypatch, value, on):
    if value is None:
        monkeypatch.delenv("SSAS_BULK_READER", raising=False)
    else:
        monkeypatch.setenv("SSAS_BULK_READER", value)
    assert ssas.bulk_reader_enabled() is on


def test_switched_off_means_no_bulk_reader(monkeypatch):
    monkeypatch.setenv("SSAS_BULK_READER", "0")
    monkeypatch.setattr(ssas, "_bulk", {"tried": True, "reader": object()})
    assert ssas._bulk_reader() is None


def test_a_missing_helper_falls_back_to_the_row_reader(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SSAS_BULK_READER", raising=False)
    monkeypatch.setattr(ssas, "BULK_DLL", tmp_path / "AdomdBulk.dll")
    monkeypatch.setattr(ssas, "_bulk", {"tried": False, "reader": None})
    assert ssas._bulk_reader() is None
    assert ssas._bulk_reader() is None  # tried once per process, not on every query
    assert capsys.readouterr().err.count("read row by row") == 1


@pytest.fixture
def fake_server(monkeypatch):
    """run_query against a pretend server: pyadomd's connection is replaced by FakeCursor rows."""
    state = {"cursors": []}

    class Connection:
        def __init__(self, conn_str):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            cur = FakeCursor([("A", 1), ("B", 2.5)], columns=("Name", "[Value]"))
            state["cursors"].append(cur)
            return cur

    monkeypatch.setitem(sys.modules, "pyadomd", types.SimpleNamespace(Pyadomd=Connection))
    monkeypatch.setattr(ssas, "_load_adomd", lambda: None)
    monkeypatch.setattr(ssas, "_network_login", nullcontext)
    monkeypatch.delenv("SSAS_BULK_READER", raising=False)
    return state


def test_run_query_reads_with_the_bulk_reader(monkeypatch, fake_server):
    bulk = FakeBulk(payload(["Name", "[Value]"], ["System.String", "System.Object"], [["A", "B"], [1, 2.5]]))
    monkeypatch.setattr(ssas, "_bulk", {"tried": True, "reader": bulk})
    df = ssas.run_query("EVALUATE x", conn_str="fake")
    assert list(df.columns) == ["Name", "[Value]"] and df["[Value]"].tolist() == [1.0, 2.5]
    assert fake_server["cursors"][0].fetched == 0


def test_run_query_reads_again_row_by_row_when_the_bulk_text_is_unreadable(monkeypatch, fake_server, capsys):
    monkeypatch.setattr(ssas, "_bulk", {"tried": True, "reader": FakeBulk("garbage")})
    df = ssas.run_query("EVALUATE x", conn_str="fake")
    assert df["Name"].tolist() == ["A", "B"] and df["[Value]"].tolist() == [1.0, 2.5]
    assert len(fake_server["cursors"]) == 2 and fake_server["cursors"][1].fetched == 2
    assert ssas._bulk["reader"] is None and "read row by row" in capsys.readouterr().err


# ---------------------------------------------------------------- the compiled reader vs pyadomd (.NET) --

@pytest.fixture(scope="module")
def dotnet():
    """pythonnet, pyadomd and the compiled bulk reader, or skip (e.g. on a Mac)."""
    try:
        ssas._load_adomd()
        import clr
        from pyadomd.pyadomd import Cursor
        reader = ssas._bulk["reader"] or ssas._load_bulk_reader()
        ssas._bulk.update(tried=True, reader=reader)  # loaded once per process, as run_query does
        clr.AddReference("System.Data")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"needs Windows with pythonnet, ADOMD.NET and adomd_bulk/AdomdBulk.dll ({exc})")
    import System
    from System.Data import DataTable
    return types.SimpleNamespace(System=System, DataTable=DataTable, Cursor=Cursor, bulk=reader)


def make_table(net, columns: dict, rows: list):
    """An in-memory .NET table: columns = {name: .NET type name}, rows = lists of .NET values."""
    table = net.DataTable()
    for name, type_name in columns.items():
        table.Columns.Add(name, net.System.Type.GetType(type_name))
    for values in rows:
        row = table.NewRow()
        for name, value in zip(columns, values):
            row[name] = net.System.DBNull.Value if value is None else value
        table.Rows.Add(row)
    return table


def cursor_on(net, table):
    """pyadomd's own cursor, reading the table instead of a server."""
    cur = net.Cursor(None)
    cur._reader = table.CreateDataReader()
    cur._field_count = cur._reader.FieldCount
    return cur


def row_reader(net, table, max_rows=None):
    return ssas._rows_one_by_one(cursor_on(net, table), max_rows, [])


def bulk_reader(net, table, max_rows=None):
    return ssas._read_rows(cursor_on(net, table), max_rows, net.bulk)


def same_value(a, b) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        return (math.isnan(a) and math.isnan(b)) or struct.pack("<d", a) == struct.pack("<d", b)
    if type(a).__module__ not in ("builtins", "datetime"):  # a .NET object left by the row reader
        return str(a) == str(b)
    return a == b


def assert_same_rows(old, new):
    assert len(old) == len(new)
    for r_old, r_new in zip(old, new):
        assert len(r_old) == len(r_new) and all(same_value(a, b) for a, b in zip(r_old, r_new)), (r_old, r_new)


def typed_table(net):
    S = net.System
    inv = S.Globalization.CultureInfo.InvariantCulture
    columns = {"text": "System.String", "whole": "System.Int64", "int32": "System.Int32", "int16": "System.Int16",
               "uint64": "System.UInt64", "real": "System.Double", "single": "System.Single",
               "money": "System.Decimal", "date": "System.DateTime", "flag": "System.Boolean", "id": "System.Guid"}
    rows = [
        ['tab\there "q" \\ \n\r café 中 \U0001F600', S.Int64(2**63 - 1), S.Int32(-5), S.Int16(7),
         S.UInt64(2**64 - 1), 0.1, S.Single(1.1), S.Decimal.Parse("1234.5678", inv),
         S.DateTime(2026, 1, 2, 3, 4, 5, 678), True, S.Guid.Parse("0f8fad5b-d9cb-469f-a165-70867728950e")],
        ["", S.Int64(0), S.Int32(0), S.Int16(0), S.UInt64(0), -0.0, S.Single(0.0), S.Decimal.Parse("0", inv),
         S.DateTime(1, 1, 1), False, S.Guid.Empty],
        ["nan", S.Int64(-2**63), S.Int32(2**31 - 1), S.Int16(-1), S.UInt64(1), float("nan"), S.Single(3.4e38),
         S.Decimal.Parse("-79228162514264337593543950335", inv), S.DateTime(9999, 12, 31, 23, 59, 59), True,
         S.Guid.Parse("00000000-0000-0000-0000-000000000001")],
        ["x", S.Int64(1), S.Int32(1), S.Int16(1), S.UInt64(1), float("inf"), S.Single(float("-inf")),
         S.Decimal.Parse("0.0000000001", inv), S.DateTime(2026, 10, 16), False, S.Guid.Empty],
    ]
    return make_table(net, columns, rows)


def test_typed_columns_match_the_row_reader_exactly(dotnet):
    table = typed_table(dotnet)
    old, new = row_reader(dotnet, table), bulk_reader(dotnet, table)
    assert_same_rows(old, new)
    assert new[1][0] is None  # empty text in a text column is None, as pyadomd gives it
    payload_text = dotnet.bulk.Read(table.CreateDataReader(), 0)
    assert json.loads(payload_text)["complete"]  # all of it came in the one call


def test_the_data_frames_match_after_number_conversion(dotnet):
    table = typed_table(dotnet)
    to_frame = lambda rows: pd.DataFrame(rows, columns=[c.ColumnName for c in table.Columns])  # noqa: E731
    old, new = to_frame(row_reader(dotnet, table)), to_frame(bulk_reader(dotnet, table))
    for df in (old, new):
        for col in df.columns:
            if df[col].dtype == object:
                try:
                    df[col] = pd.to_numeric(df[col])
                except (ValueError, TypeError):
                    pass
    pd.testing.assert_frame_equal(old, new, check_exact=True)


def test_random_numbers_come_back_bit_for_bit(dotnet):
    rng = random.Random(7)
    doubles = []
    while len(doubles) < 3000:
        value = struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0]
        if math.isfinite(value):
            doubles.append(value)
    doubles += [5e-324, 1.7976931348623157e308, 1 / 3, 2.0**53 + 2, 1e21, 1e-7, 123456789.0, 2.0]
    singles = [dotnet.System.Single(rng.uniform(-1e6, 1e6)) for _ in range(500)]
    table = make_table(dotnet, {"d": "System.Double", "s": "System.Single", "o": "System.Object"},
                       [[d, singles[i % len(singles)], d] for i, d in enumerate(doubles)])
    assert_same_rows(row_reader(dotnet, table), bulk_reader(dotnet, table))


def test_measure_columns_with_plain_values_match(dotnet):
    S = dotnet.System
    values = ["", "text \t\"q\"", S.Int64(5), S.Int32(-3), S.Int16(2), S.UInt32(7), S.Byte(200), S.SByte(-5),
              S.Char("x"), 2.5, S.Single(0.25), True, False, 0.0, S.Int64(0)]
    table = make_table(dotnet, {"m": "System.Object"}, [[v] for v in values])
    old, new = row_reader(dotnet, table), bulk_reader(dotnet, table)
    assert_same_rows(old, new)
    assert json.loads(dotnet.bulk.Read(table.CreateDataReader(), 0))["complete"]


def test_values_only_the_row_reader_converts_are_left_to_it(dotnet):
    """.NET dates and decimals inside a measure column stay .NET objects in pyadomd; the bulk reader
    stops there and the row reader reads that row and the rest, so the result is the same."""
    S = dotnet.System
    inv = S.Globalization.CultureInfo.InvariantCulture
    values = [S.Int64(1), 2.5, S.DateTime(2026, 1, 2), S.Int64(4), S.Decimal.Parse("1.5", inv), "six"]
    table = make_table(dotnet, {"n": "System.Int32", "m": "System.Object"}, [[S.Int32(i), v] for i, v in enumerate(values)])
    first = json.loads(dotnet.bulk.Read(table.CreateDataReader(), 0))
    assert not first["complete"] and first["rows"] == 2
    old, new = row_reader(dotnet, table), bulk_reader(dotnet, table)
    assert_same_rows(old, new)
    assert type(new[2][1]).__name__ == "DateTime"
    assert_same_rows(row_reader(dotnet, table, max_rows=3), bulk_reader(dotnet, table, max_rows=3))


def test_empty_cells_from_an_in_memory_table_behave_as_in_pyadomd(dotnet):
    """In-memory tables mark empty cells as DBNull (ADOMD.NET gives null): the bulk reader leaves
    those to the row reader, which turns DBNull text into '' and fails on a DBNull number, as before."""
    table = make_table(dotnet, {"text": "System.String"}, [["a"], [None], ["c"]])
    assert_same_rows(row_reader(dotnet, table), bulk_reader(dotnet, table))
    numbers = make_table(dotnet, {"n": "System.Int64"}, [[dotnet.System.Int64(1)], [None]])
    with pytest.raises(TypeError):
        row_reader(dotnet, numbers)
    with pytest.raises(TypeError):
        bulk_reader(dotnet, numbers)


def test_errors_inside_the_reader_come_through_unchanged(dotnet):
    """Server errors raised while reading reach Python with their own type and message (other code
    reads messages such as 'Column [X] is part of composite key'), not wrapped by the helper."""
    reader = make_table(dotnet, {"n": "System.Int64"}, []).CreateDataReader()
    reader.Close()
    with pytest.raises(Exception) as caught:
        dotnet.bulk.Read(reader, 0)
    assert type(caught.value).__name__ == "InvalidOperationException"
    assert "FieldCount" in str(caught.value) and "invocation" not in str(caught.value).lower()


def test_max_rows_and_empty_tables_in_the_compiled_reader(dotnet):
    S = dotnet.System
    table = make_table(dotnet, {"n": "System.Int64"}, [[S.Int64(i)] for i in range(10)])
    for limit in (None, 0, 1, 4, 10, 50):
        assert_same_rows(row_reader(dotnet, table, limit), bulk_reader(dotnet, table, limit))
    assert bulk_reader(dotnet, table, 4) == [(0,), (1,), (2,), (3,)]
    empty = make_table(dotnet, {"n": "System.Int64", "t": "System.String"}, [])
    assert bulk_reader(dotnet, empty) == [] == row_reader(dotnet, empty)


# ---------------------------------------------------------------- live server --

BOOKINGS = "GlobalTravelEngine - Bookings"
LIVE_QUERIES = [
    ("SELECT [CUBE_NAME], [LAST_DATA_UPDATE] FROM $SYSTEM.MDSCHEMA_CUBES", None),
    ("SELECT * FROM $SYSTEM.MDSCHEMA_MEASURES", None),
    ("EVALUATE SUMMARIZECOLUMNS('Calendar'[Year], \"Sale\", [Sale], \"Markup\", [Markup], \"Sale LY\", [Sale LY])", None),
    ('EVALUATE ROW("tab", "a" & UNICHAR(9) & "b", "quote", "say ""hi""", "uni", "caf" & UNICHAR(233) & UNICHAR(128512), '
     '"empty", "", "blank", BLANK(), "flag", TRUE(), "money", CURRENCY(12.34), "when", DATE(2026,1,2) + TIME(3,4,5))', None),
    ("EVALUATE SUMMARIZECOLUMNS('Calendar'[Year], \"Last date\", MAX('Calendar'[Date]), \"Sale\", [Sale])", None),
    ("EVALUATE SUMMARIZECOLUMNS('Create Date'[Create Date], \"Sale\", [Sale], \"Avg Sale\", [Avg Sale])", 50),
]


def needs_server():
    if config.resolve_source() != "ssas" or not config.SSAS_SERVER:
        pytest.skip("needs the live server")


@pytest.mark.live
@pytest.mark.parametrize("query, max_rows", LIVE_QUERIES)
def test_live_both_readers_give_the_same_result(monkeypatch, query, max_rows):
    needs_server()
    results = {}
    for mode in ("0", "1"):
        monkeypatch.setenv("SSAS_BULK_READER", mode)
        results[mode] = ssas.run_query(query, max_rows=max_rows, database=BOOKINGS)
    old, new = results["0"], results["1"]
    assert max_rows is None or len(new) == max_rows
    for df in (old, new):  # .NET dates left in a measure column by the row reader: compare their text
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].map(lambda v: v if v is None or type(v).__module__ in ("builtins", "datetime")
                                      else str(v))
    pd.testing.assert_frame_equal(old, new, check_exact=False, rtol=1e-9, atol=1e-9)
    assert os.getenv("SSAS_BULK_READER") == "1" and ssas._bulk["reader"] is not None


@pytest.mark.live
def test_live_a_capped_read_does_not_wait_for_the_rows_beyond_the_cap(monkeypatch):
    """About 130,000 places, cut at 5,000: the server stops sending instead of streaming the rest (~22 s)."""
    needs_server()
    monkeypatch.delenv("SSAS_BULK_READER", raising=False)
    started = time.perf_counter()
    df = ssas.run_query("EVALUATE SUMMARIZECOLUMNS('Areas'[Area], 'Areas'[Area.UniqueName])", max_rows=5000,
                        database=BOOKINGS)
    assert len(df) == 5000 and time.perf_counter() - started < 12
