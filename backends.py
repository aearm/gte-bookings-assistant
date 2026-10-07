"""Picks where data comes from: the live Analysis Services model (Windows) or local files."""
import platform
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd

import config


@dataclass
class Backend:
    key: str                 # "ssas" or "local"
    label: str               # shown in the sidebar
    language: str            # "DAX" or "SQL"
    schema_file: Path
    run: Callable[[str, int | None], pd.DataFrame]
    build_schema: Callable[[], tuple[str, int, int]]
    schema_summary: Callable[[int, int], str]
    supports_schedule: bool
    date_literal: Callable[[date], str]   # how a date is written in a query
    data_as_of: Callable[[], str]          # when the data was last refreshed, or ""


def resolve_source() -> str:
    if config.DATA_SOURCE in ("ssas", "local"):
        return config.DATA_SOURCE
    return "ssas" if platform.system() == "Windows" else "local"


def get_backend() -> Backend:
    if resolve_source() == "ssas":
        import ssas

        def run(query, max_rows=None):
            return ssas.clean_column_names(ssas.run_query(query, max_rows=max_rows))

        return Backend(
            key="ssas",
            label=f"Live model: **{config.SSAS_DATABASE or 'not set'}**  \nServer: `{config.SSAS_SERVER or 'not set'}`",
            language="DAX",
            schema_file=config.SCHEMA_FILE,
            run=run,
            build_schema=ssas.build_schema_text,
            schema_summary=lambda cols, meas: f"Found {meas} measures and {cols} columns.",
            supports_schedule=True,
            date_literal=lambda d: f"DATE({d.year},{d.month},{d.day})",
            data_as_of=ssas.last_data_update,
        )

    import localdb
    return Backend(
        key="local",
        label="Local data files: **data/local**  \n(sample or exported data, no server)",
        language="SQL",
        schema_file=config.LOCAL_SCHEMA_FILE,
        run=localdb.run_query,
        build_schema=localdb.build_schema_text,
        schema_summary=lambda cols, tables: f"Found {tables} table(s) with {cols} columns.",
        supports_schedule=False,
        date_literal=lambda d: f"DATE '{d.isoformat()}'",
        data_as_of=lambda: "",
    )
