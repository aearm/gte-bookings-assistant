"""Build the data layer: Claude reads every connected cube once and learns what each one is for,
what its numbers and dates mean, and how cubes join (see data_layer.py). Run it once after
installing (after the API key and server are saved on the Settings page), and again after cubes
change. The Cubes page has the same button.

Run:  python build_layer.py            every connected cube
      python build_layer.py --all      connect every cube on the server first, then build
      python build_layer.py --update   only new and changed cubes are studied again
"""
import sys
import time

import config
import cubes
import data_layer


def main(args: list[str]) -> int:
    sys.stdout.reconfigure(errors="replace")  # ✓ and ✗ in the progress lines, on any console
    cubes.migrate()
    if "--all" in args:
        if config.resolve_source() != "ssas":
            print("--all only applies to the live server; local mode uses the files in data/local.")
        else:
            import ssas
            names = ssas.list_databases()["CATALOG_NAME"].tolist()
            cubes.set_enabled(sorted(names))
            print(f"Connected all {len(names)} cubes on {config.SSAS_SERVER}.")
    started = time.time()
    try:
        layer = data_layer.build(only_changed="--update" in args, on_progress=lambda text: print(" ", text, flush=True))
    except Exception as exc:  # a friendly line instead of a long traceback
        print(f"Could not build the data layer: {exc}")
        return 1
    print(f"Done in {(time.time() - started) / 60:.1f} minutes: {len(layer['cubes'])} cube(s), "
          f"{len(layer['entities'])} shared dimension(s). Saved in {data_layer.LAYER_FILE}")
    for cube, problem in layer.get("errors", {}).items():
        print(f"  Left out {cubes.label(cube)}: {problem}")
    return 1 if layer.get("errors") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
