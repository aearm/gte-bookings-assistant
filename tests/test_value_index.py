"""The value index: small columns in memory, big ones in the shared disk store (models/values.db),
answering the same way."""
import json
import sqlite3

import value_index

COUNTRY = "'Countries'[Country]"
STATUS = "'Status'[Status]"
COUNTRIES = [["UNITED ARAB EMIRATES", 50], ["SPAIN", 20], ["Saudi Arabia", 10], ["NOWHERE", 0]]


def save(cube, columns, measure=""):
    index = value_index.for_cube(cube)
    index.save({c: {"group_with": [], "values": v} for c, v in columns.items()}, measure)
    return index


def test_big_columns_live_on_disk_and_answer_the_same(app_dirs, monkeypatch):
    monkeypatch.setattr(value_index, "MEMORY_LIMIT", 3)
    index = save("Bookings", {COUNTRY: COUNTRIES, STATUS: [["Confirmed", 9], ["Cancelled", 3]]}, "[Bookings]")
    in_file = json.loads(index.path.read_text(encoding="utf-8"))["columns"]
    assert in_file[COUNTRY] == {"group_with": [], "on_disk": True, "count": 4}  # not kept in memory
    assert "values" in in_file[STATUS]
    assert index.indexed(COUNTRY) and index.disk_columns() == [COUNTRY] and index.live_columns() == []

    assert index.exact("uae") == [{"column": COUNTRY, "value": "UNITED ARAB EMIRATES", "count": 50}]  # initials
    assert {(h["text"], h["value"]) for h in index.exact_many(["Spain", "confirmed", "UAE", "Paris"])} == {
        ("Spain", "SPAIN"), ("confirmed", "Confirmed"), ("UAE", "UNITED ARAB EMIRATES")}
    assert index.lookup(COUNTRY, ["spain", "Atlantis"]) == {"spain": "SPAIN", "Atlantis": None}
    assert index.has_no_data(COUNTRY, "NOWHERE") and not index.has_no_data(COUNTRY, "SPAIN")
    assert index.search("saudi")[0]["value"] == "Saudi Arabia"
    assert [h["value"] for h in index.search("spian", column=COUNTRY)] == ["SPAIN"]  # a typo
    assert sorted(dict(index.all_values())[COUNTRY]) == sorted(v for v, _ in COUNTRIES)


def test_a_value_in_several_cubes_is_stored_once(app_dirs, monkeypatch):
    monkeypatch.setattr(value_index, "MEMORY_LIMIT", 3)
    bookings = save("Bookings", {COUNTRY: COUNTRIES})
    payments = save("Payments", {COUNTRY: [["SPAIN", 7], ["EGYPT", 1], ["FRANCE", 2], ["ITALY", 1]]})
    con = sqlite3.connect(value_index.store_file())
    count = lambda sql: con.execute(sql).fetchone()[0]
    assert count("SELECT COUNT(*) FROM vals WHERE value = 'SPAIN'") == 1
    assert payments.lookup(COUNTRY, ["spain"]) == {"spain": "SPAIN"} and payments.exact("uae") == []  # its own values
    assert payments.exact("spain")[0]["count"] == 7 and bookings.exact("spain")[0]["count"] == 20

    save("Bookings", {COUNTRY: [["SPAIN", 21]]})  # read again, now small: back in memory, off the disk
    assert count("SELECT COUNT(*) FROM counts WHERE cube = 'bookings'") == 0
    assert count("SELECT COUNT(*) FROM vals WHERE value = 'UNITED ARAB EMIRATES'") == 0  # no cube has it
    assert bookings.exact("spain") == [{"column": COUNTRY, "value": "SPAIN", "count": 21}]
    con.close()


def test_an_old_index_moves_its_big_columns_to_disk_when_read(app_dirs, monkeypatch):
    monkeypatch.setattr(value_index, "MEMORY_LIMIT", 3)
    index = value_index.for_cube("Bookings")
    index.path.parent.mkdir(parents=True, exist_ok=True)
    old = {"built": "2026-10-07T10:00:00", "measure": "[Bookings]",
           "columns": {COUNTRY: {"group_with": [], "values": COUNTRIES}}}
    index.path.write_text(json.dumps(old), encoding="utf-8")
    assert index.exact("uae")[0]["value"] == "UNITED ARAB EMIRATES"
    in_file = json.loads(index.path.read_text(encoding="utf-8"))
    assert in_file["built"] == "2026-10-07T10:00:00" and in_file["columns"][COUNTRY]["on_disk"]
