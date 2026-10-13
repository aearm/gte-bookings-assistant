import json

import pandas as pd

import cubes
import data_layer
import llm
import ssas
import value_index

DAX_SCHEMA = """# Model: Sales
Server: x | Type: Multidimensional (cube) | Read on 2026-10-13 17:06

## Measures (use these for any numbers)
- [Final Sales]  (in 'Bookings') | format: #,##0
- [Reservations Count]  (in 'Bookings')
- [Final Sales LY]  (in 'Bookings LY')

## Tables and columns (use these to group and filter)

### 'Customers'
- 'Customers'[Code] (Text) | group with 'Customers'[Code.Key0] | values: "A1" (3), "B2" (2)
- 'Customers'[Cliente] (Text) | group with 'Customers'[Cliente.Key0] | 1,234 values, e.g. "Atlas"

### 'Create Date'
- 'Create Date'[Create Date] (Date/time) | sort by 'Create Date'[Create Date.Fecha ISO DESC]
"""


def test_schema_names_and_fingerprint():
    names = data_layer.schema_names(DAX_SCHEMA)
    assert names["measures"] == {"[Final Sales]", "[Reservations Count]", "[Final Sales LY]"}
    assert names["columns"]["'Customers'[Code]"] == "Text"
    assert names["tables"] == {"Customers", "Create Date"}
    assert data_layer.date_columns(DAX_SCHEMA) == ["'Create Date'[Create Date]"]
    # new values or counts don't change the fingerprint; a new column does
    same = DAX_SCHEMA.replace('"A1" (3)', '"A1" (300), "C3" (1)').replace("17:06", "18:00")
    assert data_layer.fingerprint(same) == data_layer.fingerprint(DAX_SCHEMA)
    assert data_layer.fingerprint(DAX_SCHEMA + "- 'Customers'[Market] (Text)\n") != data_layer.fingerprint(DAX_SCHEMA)


def test_profiles_keep_only_real_names():
    profile = {
        "measures": [{"name": "[Final Sales]", "label": "Sales"}, {"name": "[Made Up]", "label": "X"}],
        "default_date": "'Booking'[Date]",
        "dates": [{"column": "'Create Date'[Create Date]", "meaning": "made"}],
        "dimensions": [{"table": "Customers", "entity": "customer", "key_column": "'Customers'[Code]",
                        "name_column": "'Customers'[Name]"},
                       {"table": "Ghost", "entity": "spaceship", "key_column": "'Ghost'[Id]", "name_column": ""}],
    }
    clean = data_layer._clean_profile(profile, DAX_SCHEMA, "DAX")
    assert [m["name"] for m in clean["measures"]] == ["[Final Sales]"]
    assert clean["default_date"] == "'Create Date'[Create Date]"  # the made-up one is replaced
    assert clean["dimensions"] == [{"table": "Customers", "entity": "customer", "key_column": "'Customers'[Code]",
                                    "name_column": ""}]
    assert any("[Made Up]" in w for w in clean["warnings"])


def _sets():
    customers = {f"C{i}" for i in range(100)}
    return {
        ("Bookings", "'Customers'[Code]"): customers,
        ("Payments", "'Customers'[Code]"): {f"C{i}" for i in range(80)} | {"X1", "X2"},
        ("Stats", "'Cliente'[Customer Code]"): {f"C{i}" for i in range(50, 100)},
        ("Stats", "'Hoteles'[Codigo]"): {f"H{i}" for i in range(30)},
        ("Allotments", "'Hotels'[JP Code]"): {f"H{i}" for i in range(20)} | {"H999"},
    }


def test_entity_members_measure_matches_against_the_hub():
    profiles = {
        "Bookings": {"dimensions": [{"table": "Customers", "entity": "customer", "key_column": "'Customers'[Code]",
                                     "name_column": ""}]},
        "Payments": {"dimensions": [{"table": "Customers", "entity": "customer", "key_column": "'Customers'[Code]",
                                     "name_column": ""}]},
        "Stats": {"dimensions": [{"table": "Cliente", "entity": "customer", "key_column": "'Cliente'[Customer Code]",
                                  "name_column": ""}]},
    }
    members = data_layer.entity_members(profiles, _sets())
    by_cube = {m["cube"]: m for m in members["customer"]}
    assert by_cube["Bookings"].get("hub")
    assert by_cube["Payments"]["key_match"]["shared"] == 80
    assert by_cube["Payments"]["key_match"]["of_smaller"] == round(80 / 82, 3)
    assert by_cube["Stats"]["key_match"]["of_smaller"] == 1.0


def test_column_links_find_shared_values_the_profiles_missed():
    links = data_layer.column_links(_sets(), already=set())
    pairs = {(x["a"]["column"], x["b"]["column"]) for x in links}
    assert ("'Hotels'[JP Code]", "'Hoteles'[Codigo]") in pairs  # found from the values alone
    assert all(x["a"]["cube"] != x["b"]["cube"] for x in links)


def test_conform_keeps_only_real_join_columns(app_dirs, monkeypatch):
    for cube, text in {"Bookings": DAX_SCHEMA, "Payments": DAX_SCHEMA}.items():
        cubes.schema_file(cube).write_text(text, encoding="utf-8")
    answer = {"entities": [
        {"entity": "customer", "label": "Customer", "description": "Agencies", "join_notes": "upper(trim)",
         "members": [{"cube": "Bookings", "join_column": "'Customers'[Code]", "display_column": "'Customers'[Cliente]",
                      "match": "high"},
                     {"cube": "Payments", "join_column": "'Customers'[Code]", "display_column": "'X'[Y]", "match": "high"},
                     {"cube": "Payments", "join_column": "'Nope'[Nope]", "display_column": "", "match": "high"}]},
        {"entity": "hotel", "label": "Hotel", "description": "", "join_notes": "",
         "members": [{"cube": "Bookings", "join_column": "'Hotels'[Code]", "display_column": "", "match": "high"}]}],
        "routing": [{"topic": "Sales", "cube": "Bookings", "why": "source"}, {"topic": "X", "cube": "Nowhere", "why": ""}],
        "cross_cube_questions": ["Sales and payments by customer"]}
    monkeypatch.setattr(llm, "_structured_call", lambda *a, **k: json.loads(json.dumps(answer)))
    out = data_layer.conform({"Bookings": {}, "Payments": {}}, {}, [])
    assert [e["entity"] for e in out["entities"]] == ["customer"]  # the hotel only had one real member
    assert len(out["entities"][0]["members"]) == 2
    assert out["entities"][0]["members"][1]["display_column"] == ""
    assert [r["cube"] for r in out["routing"]] == ["Bookings"]


LOCAL_PROFILE = {
    "label": "Bookings and agencies", "subject_area": "Sales", "description": "Hotel bookings with agencies.",
    "grain": "One booking", "use_for": ["sales by agency"], "not_for": [], "default_date": '"Booking Date"',
    "dates": [{"column": '"Booking Date"', "meaning": "day the booking was made"}],
    "measures": [{"name": 'SUM("Sales USD")', "label": "Sales", "synonyms": ["revenue"], "meaning": "Sales",
                  "unit": "currency", "aggregation": "additive"}],
    "variants": "", "dimensions": [{"table": "agencies", "entity": "customer", "meaning": "Agencies",
                                    "key_column": '"Agency"', "name_column": '"Agency"'}],
    "filters": [{"meaning": "valid bookings", "filter": "\"Status\" = 'Confirmed'"}],
    "example_questions": ["Sales by account manager"],
}


def build_local_layer(monkeypatch):
    calls = []

    def fake(system, tool, user, **kwargs):
        calls.append((tool["name"], kwargs))
        return json.loads(json.dumps(LOCAL_PROFILE))
    monkeypatch.setattr(llm, "_structured_call", fake)
    return data_layer.build(on_progress=lambda text: None), calls


def test_build_in_local_mode(app_dirs, monkeypatch):
    layer, calls = build_local_layer(monkeypatch)
    assert calls == [("submit_profile", {"model": data_layer.config.CLAUDE_LAYER_MODEL, "effort": "high",
                                         "max_tokens": 48000})]
    assert list(layer["cubes"]) == [cubes.LOCAL] and layer["language"] == "SQL"
    assert data_layer.LAYER_FILE.exists() and data_layer.CATALOG_FILE.exists()
    status = data_layer.status()
    assert status["ready"] and not status["changed"] and not status["missing"]
    catalog = data_layer.catalog_text()
    assert "### Bookings and agencies" in catalog and 'SUM("Sales USD") Sales (currency, additive' in catalog
    assert data_layer.example_questions() == ["Sales by account manager"]
    # both local tables were read into the physical layer with their values
    index = value_index.for_cube(cubes.LOCAL)
    assert [h["value"] for h in index.search("Nile Star")][:1] == ["Nile Star"]  # only in agencies.csv
    assert index.lookup('"Status"', ["confirmed"]) == {"confirmed": "Confirmed"}  # from bookings.csv
    assert '## Table "agencies"' in data_layer.cube_details(cubes.LOCAL)


def test_rebuild_only_studies_changed_cubes(app_dirs, monkeypatch):
    build_local_layer(monkeypatch)
    calls = []
    monkeypatch.setattr(llm, "_structured_call", lambda *a, **k: calls.append(1) or LOCAL_PROFILE)
    data_layer.build(only_changed=True)
    assert calls == []  # same structure: the earlier profile is kept
    pd.DataFrame({"New": ["a"]}).to_csv(app_dirs / "local" / "extra.csv", index=False)
    data_layer.build(only_changed=True)
    assert calls == [1]


def test_values_are_read_on_the_right_cube_in_every_thread(app_dirs, monkeypatch):
    """The value index used to come out empty: worker threads queried no cube at all."""
    import re
    seen = []

    def fake_run_query(query, max_rows=None, conn_str=None, database=None):
        seen.append(ssas.current_database(database))
        col = re.search(r"'T'\[(C\d)\]", query).group(1)
        if '"n"' in query:
            return pd.DataFrame({f"'T'[{col}]": ["a", "b"], "[n]": [3, 4]})
        return pd.DataFrame({f"'T'[{col}]": ["a", "b"]})
    monkeypatch.setattr(ssas, "run_query", fake_run_query)
    monkeypatch.setattr(ssas, "_level_cardinality", lambda: {})
    monkeypatch.setattr(ssas.config, "SSAS_DATABASE", "")
    cols = [{"table": "T", "column": f"C{i}", "type": "Text", "group_with": []} for i in range(6)]
    with ssas.using("Cube X"):
        ssas._add_values(cols, "[n]")
    assert seen and set(seen) == {"Cube X"}
    index = value_index.for_cube("Cube X")
    assert len(index.columns()) == 6
    assert index.lookup("'T'[C3]", ["B"]) == {"B": "b"}
