"""Test the data connection and save the data structure Claude is allowed to use.

Run:  python build_schema.py
Re-run whenever measures/tables are added (the app also has a Refresh button).
"""
import sys

from backends import get_backend


def main() -> int:
    backend = get_backend()
    source = "live Analysis Services model" if backend.key == "ssas" else "local files in data/local"
    print(f"Reading the {source} ...")
    try:
        text, a, b = backend.build_schema()
    except Exception as exc:  # show a friendly message instead of a long traceback
        print("\nCould not read the data.")
        print(f"Reason: {exc}")
        if backend.key == "ssas":
            print("\nTry: python test_connection.py  (checks login and connection settings)")
        return 1

    backend.schema_file.write_text(text, encoding="utf-8")
    print(f"Connected. {backend.schema_summary(a, b)}")
    print(f"Saved to {backend.schema_file.name}. Add notes for Claude in business_notes.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
