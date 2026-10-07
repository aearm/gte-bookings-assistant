"""Scheduled pull: runs every saved query in queries/*.dax and saves the results.

Run:  python pull.py   (or schedule run_pull.bat with Windows Task Scheduler)
Output:
  data/snapshots/<name>.csv              - latest copy (always overwritten)
  data/snapshots/<name>_<YYYY-MM-DD>.csv - dated copy, so you keep history
"""
import sys
from datetime import datetime

import config
import ssas


def main() -> int:
    queries = sorted(config.QUERIES_DIR.glob("*.dax"))
    if not queries:
        print("No saved queries yet. In the app, open 'DAX query' under an answer "
              "and click 'Save this query for scheduled pulls'.")
        return 0

    config.SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    failures = 0
    for path in queries:
        try:
            df = ssas.clean_column_names(ssas.run_query(path.read_text(encoding="utf-8")))
            df.to_csv(config.SNAPSHOTS_DIR / f"{path.stem}.csv", index=False)
            df.to_csv(config.SNAPSHOTS_DIR / f"{path.stem}_{stamp}.csv", index=False)
            print(f"OK    {path.name}: {len(df)} rows")
        except Exception as exc:
            failures += 1
            print(f"FAIL  {path.name}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
