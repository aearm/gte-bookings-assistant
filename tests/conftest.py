"""Test set-up: every test runs against temporary folders (models/, dashboards.json, data/local)
in local mode, so the real company files and the live server are never touched. Tests marked
`live` use the real server and Claude API and only run with RUN_LIVE=1."""
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config as app_config  # noqa: E402
import cubes  # noqa: E402
import data_layer  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "live: uses the real Analysis Services server and Claude API (RUN_LIVE=1)")


def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set RUN_LIVE=1 to run against the real server and Claude")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


BOOKINGS = pd.DataFrame({
    "Booking ID": [f"BK{i}" for i in range(12)],
    "Booking Date": pd.to_datetime(["2026-01-05", "2026-01-20", "2026-02-03", "2026-02-14", "2026-03-01",
                                    "2026-03-09", "2026-03-30", "2026-04-02", "2026-04-15", "2026-05-01",
                                    "2026-05-02", "2026-05-20"]),
    "Status": ["Confirmed"] * 9 + ["Cancelled"] * 3,
    "Agency": ["Desert Pearl Tours", "Coral Bay Travel", "Lotus Travel House", "Desert Pearl Tours",
               "Coral Bay Travel", "Atlas Voyages", "Atlas Voyages", "Lotus Travel House", "Desert Pearl Tours",
               "Coral Bay Travel", "Atlas Voyages", "Lotus Travel House"],
    "Destination Country": ["Spain", "Egypt", "Qatar", "Spain", "France", "Italy", "Spain", "Egypt", "Qatar",
                            "France", "Italy", "Spain"],
    "Sales USD": [100.0, 250.5, 80.0, 120.0, 300.0, 90.0, 60.0, 410.0, 75.5, 33.0, 12.0, 220.0],
})
AGENCIES = pd.DataFrame({
    "Agency": ["Desert Pearl Tours", "Coral Bay Travel", "Lotus Travel House", "Atlas Voyages", "Nile Star"],
    "Account Manager": ["Sara", "Omar", "Sara", "Lina", "Omar"],
    "Segment": ["Key account", "Standard", "Standard", "Key account", "New"],
})


@pytest.fixture
def app_dirs(tmp_path, monkeypatch):
    """Local mode with two small tables, and empty models / dashboards in a temporary folder."""
    data = tmp_path / "local"
    data.mkdir()
    BOOKINGS.to_csv(data / "bookings.csv", index=False)
    AGENCIES.to_csv(data / "agencies.csv", index=False)
    models = tmp_path / "models"
    monkeypatch.setattr(app_config, "DATA_SOURCE", "local")
    monkeypatch.setattr(app_config, "LOCAL_DATA_DIR", data)
    monkeypatch.setattr(app_config, "MODELS_DIR", models)
    monkeypatch.setattr(app_config, "DASHBOARDS_FILE", tmp_path / "dashboards.json")
    monkeypatch.setattr(app_config, "DASHBOARD_FILE", tmp_path / "dashboard.json")
    monkeypatch.setattr(app_config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(app_config, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(app_config, "HISTORY_FILE", tmp_path / "history.jsonl")
    monkeypatch.setattr(app_config, "LOCAL_SCHEMA_FILE", tmp_path / "schema_local.md")
    monkeypatch.setattr(cubes, "CUBES_FILE", models / "cubes.json")
    monkeypatch.setattr(data_layer, "LAYER_DIR", models / "data_layer")
    monkeypatch.setattr(data_layer, "LAYER_FILE", models / "data_layer" / "layer.json")
    monkeypatch.setattr(data_layer, "CATALOG_FILE", models / "data_layer" / "catalog.md")
    monkeypatch.setattr(app_config, "ANTHROPIC_API_KEY", "sk-ant-test")
    data_layer._cache.update(mtime=None, data={})
    return tmp_path
