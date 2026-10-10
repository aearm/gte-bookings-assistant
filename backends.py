"""Where data comes from: a live Analysis Services cube (Windows) or local files. A Backend is
bound to one cube: its queries, value lookups and files (structure, value index) all belong to it."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd

import config
import cubes
import value_index


@dataclass
class Backend:
    key: str                 # "ssas" or "local"
    cube: str                # the cube (Analysis Services database) this backend queries
    label: str               # shown in the sidebar
    language: str            # "DAX" or "SQL"
    schema_file: Path
    run: Callable[[str, int | None], pd.DataFrame]
    build_schema: Callable[[], tuple[str, int, int]]
    schema_summary: Callable[[int, int], str]
    supports_schedule: bool
    date_literal: Callable[[date], str]   # how a date is written in a query
    data_as_of: Callable[[], str]          # when the data was last refreshed, or ""
    find_values: Callable[[str, list, list], dict]   # (column, group_with, values) -> {value: real value or None}
    search_values: Callable[..., list]               # (column, group_with, text, limit) -> similar real values

    @property
    def index(self) -> value_index.ValueIndex:
        return value_index.for_cube(self.cube)

    def schema_text(self) -> str:
        return self.schema_file.read_text(encoding="utf-8") if self.schema_file.exists() else ""

    def refresh_schema(self) -> str:
        """Read the cube's structure and values again; returns a short summary."""
        text, a, b = self.build_schema()
        self.schema_file.write_text(text, encoding="utf-8")
        return self.schema_summary(a, b)


def resolve_source() -> str:
    return config.resolve_source()


def get_backend(cube: str | None = None) -> Backend:
    """The backend for a cube (default: the first connected cube)."""
    if resolve_source() == "ssas":
        import ssas
        cube = cube or cubes.default() or config.SSAS_DATABASE

        def run(query, max_rows=None):
            return ssas.clean_column_names(ssas.run_query(query, max_rows=max_rows, database=cube))

        return Backend(
            key="ssas",
            cube=cube,
            label=f"Cube: **{cubes.label(cube) or 'not set'}**  \nServer: `{config.SSAS_SERVER or 'not set'}`",
            language="DAX",
            schema_file=cubes.schema_file(cube),
            run=run,
            build_schema=lambda: ssas.build_schema_text(cube),
            schema_summary=lambda cols, meas: f"Found {meas} measures and {cols} columns.",
            supports_schedule=True,
            date_literal=lambda d: f"DATE({d.year},{d.month},{d.day})",
            data_as_of=lambda: ssas.last_data_update(cube),
            find_values=lambda column, gw, values: ssas.find_values(column, gw, values, database=cube),
            search_values=lambda column, gw, text, limit=6: ssas.search_values(column, gw, text, limit, database=cube),
        )

    import localdb
    return Backend(
        key="local",
        cube=cubes.LOCAL,
        label="Local data files: **data/local**  \n(sample or exported data, no server)",
        language="SQL",
        schema_file=cubes.schema_file(cubes.LOCAL),
        run=localdb.run_query,
        build_schema=localdb.build_schema_text,
        schema_summary=lambda cols, tables: f"Found {tables} table(s) with {cols} columns.",
        supports_schedule=False,
        date_literal=lambda d: f"DATE '{d.isoformat()}'",
        data_as_of=lambda: "",
        find_values=localdb.find_values,
        search_values=localdb.search_values,
    )
