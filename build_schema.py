"""Read the structure and values of the connected cubes (what Claude is allowed to use).

Run:  python build_schema.py                  (every connected cube)
      python build_schema.py "Cube name"      (one cube)
Re-run whenever measures, columns or values change (the Cubes page has a button for this too).
"""
import sys

import cubes
from backends import get_backend


def main() -> int:
    cubes.migrate()
    names = sys.argv[1:] or cubes.enabled()
    if not names:
        print("No cube is connected yet: choose them on the app's Cubes page.")
        return 1
    failed = 0
    for cube in names:
        backend = get_backend(cube)
        print(f"Reading {cubes.label(cube)} ...")
        try:
            print(f"  {backend.refresh_schema()} Saved to {backend.schema_file}")
        except Exception as exc:  # show a friendly message instead of a long traceback
            failed += 1
            print(f"  Could not read it: {exc}")
            if backend.key == "ssas":
                print("  Try: python test_connection.py  (checks login and connection settings)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
