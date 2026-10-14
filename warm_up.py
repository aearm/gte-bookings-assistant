"""Gets the slow first-time work out of the way when the server starts, in the background, so the
first person of the day doesn't wait for it: loading the connector to Analysis Services and opening
a first connection, and reading every cube's value index and the index cards into memory."""
import sys
import threading

import config

_started = threading.Event()


def _run() -> None:
    try:
        import data_layer
        import routing
        import value_index
        for cube in data_layer.layer_cubes():
            value_index.for_cube(cube).load()
        routing.cards_text()
        if config.resolve_source() == "ssas" and config.SSAS_SERVER:
            import ssas
            ssas.list_databases()  # loads ADOMD.NET and opens a first connection
    except Exception:
        pass  # warming up is a help, never a requirement


def start() -> None:
    """Runs once per server process (later calls do nothing), only in the real app server (started
    with `streamlit run`, or start_server.py) - not in tests or scripts, which end while it would still
    be talking to the server through .NET, and that crashes Python's .NET bridge on exit."""
    from streamlit import runtime
    if not _started.is_set() and runtime.exists() and "streamlit" in sys.argv[0].lower():
        _started.set()
        threading.Thread(target=_run, name="warm-up", daemon=True).start()
