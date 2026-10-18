"""Prepares an end-to-end test run (run by Playwright just before it starts the test server):
- a throwaway data folder and dashboards file (APP_DATA_DIR / APP_DASHBOARDS_FILE): the real ones are
  never touched;
- an admin sign-in token, so the tests sign in without anyone's password;
- the reference numbers of questions.json, from simple one-measure queries on the cubes (no Claude).
Writes e2e/.state.json for the tests."""
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
sys.path.insert(0, str(BASE))
os.chdir(BASE)

data_dir = Path(os.environ["APP_DATA_DIR"])
if data_dir.resolve() == (BASE / "data").resolve():
    sys.exit("APP_DATA_DIR must not be the app's real data folder.")
shutil.rmtree(data_dir, ignore_errors=True)
data_dir.mkdir(parents=True)
# the test dashboard: fixed charts that follow the dashboard's period (e2e/charts.json), so the tests do
# not depend on what is on the real dashboards; then the dashboards the app ships with (the server is
# told not to add them itself, which would put them first)
import builtin_dashboards  # noqa: E402

charts = json.loads((HERE / "charts.json").read_text(encoding="utf-8"))["charts"]
Path(os.environ["APP_DASHBOARDS_FILE"]).write_text(json.dumps({"dashboards": [
    {"id": "e2e-main", "name": "Test dashboard", "charts": charts}, *builtin_dashboards.all_dashboards()]}),
    encoding="utf-8")

import eval_set  # noqa: E402  (after the folders are set, as it reads config)
import secrets_store  # noqa: E402

questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))["questions"]
references = {}
for q in questions:
    for check in q["checks"]:
        try:
            references[f"{q['id']}:{check['name']}"] = eval_set.reference(check)
        except Exception as exc:  # the test that needs it fails with this reason
            references[f"{q['id']}:{check['name']}"] = f"FAILED: {str(exc).splitlines()[0][:200]}"

state = {"admin_token": secrets_store.make_login_token(1), "references": references,
         "data_dir": str(data_dir)}
(HERE / ".state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
print(f"e2e prepared: {len(references)} reference numbers in {data_dir}")
