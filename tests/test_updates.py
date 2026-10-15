"""Updating from a GitHub release: the code changes, everything belonging to the installation stays."""
import io
import json
import urllib.error
import zipfile

import pytest

import updates

USER_DATA = {".env": "ANTHROPIC_API_KEY=kept", "dashboards.json": '{"dashboards": ["mine"]}',
             "glossary.json": "{}", "models/bookings/value_index.json": "{}", "models/values.db": "db",
             "data/answers.db": "answers", "data/usage.jsonl": "{}", "data/local/README.txt": "my notes",
             ".venv/Lib/site.py": "venv"}


def write(root, files: dict):
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")


@pytest.fixture
def install(tmp_path, monkeypatch):
    """An installation of 1.0.0 with its users' data, and the 1.1.0 release next to it."""
    here, release = tmp_path / "app", tmp_path / "release"
    write(here, {"app.py": "old app", "VERSION": "1.0.0", "charts.py": "same", "old_module.py": "dropped later",
                 "requirements.txt": "streamlit", **USER_DATA})
    write(here, {"data/installed_files.json": json.dumps({"files": ["app.py", "VERSION", "charts.py", "old_module.py",
                                                                    "requirements.txt"]})})
    write(release, {"app.py": "new app", "VERSION": "1.1.0", "charts.py": "same", "new_module.py": "new",
                    "requirements.txt": "streamlit", "data/local/README.txt": "release notes",
                    "data/local/sample.csv": "a,b", "models/should_not_arrive.json": "x"})
    monkeypatch.setattr(updates, "BASE", here)
    return here, release


def text(root, rel):
    return (root / rel).read_text(encoding="utf-8")


def test_an_update_changes_the_code_and_keeps_every_users_data(install):
    here, release = install
    done = updates.apply(release, "1.1.0")
    assert text(here, "app.py") == "new app" and updates.current_version() == "1.1.0"
    assert text(here, "new_module.py") == "new" and not (here / "old_module.py").exists()  # dropped by the release
    assert "charts.py" not in done["written"]  # unchanged files aren't rewritten
    for rel, content in USER_DATA.items():
        assert text(here, rel) == content, rel  # settings, dashboards, data layer, history, environment
    assert text(here, "data/local/sample.csv") == "a,b"  # new sample file added; the edited README kept
    assert not (here / "models/should_not_arrive.json").exists()
    assert "app.py" in json.loads(text(here, "data/installed_files.json"))["files"]
    with zipfile.ZipFile(done["backup"]) as z:
        assert {"app.py", "VERSION", "old_module.py", "data/installed_files.json"} <= set(z.namelist())

    updates.rollback(done)
    assert text(here, "app.py") == "old app" and text(here, "old_module.py") == "dropped later"
    assert not (here / "new_module.py").exists() and not (here / "data/local/sample.csv").exists()
    assert updates.current_version() == "1.0.0"
    assert "old_module.py" in json.loads(text(here, "data/installed_files.json"))["files"]


def test_a_failed_update_puts_the_previous_version_back(install, monkeypatch):
    here, release = install
    write(release, {"requirements.txt": "streamlit\nnew-library"})
    monkeypatch.setattr(updates, "install_requirements", lambda: (_ for _ in ()).throw(RuntimeError("pip failed")))
    status = updates.run_update(release, "1.1.0", app_pid=0, restart=False)
    assert not status["ok"] and "pip failed" in status["error"] and "put back" in status["error"]
    assert text(here, "app.py") == "old app" and updates.current_version() == "1.0.0"
    assert updates.last_status()["to"] == "1.1.0" and not updates.updating()

    monkeypatch.setattr(updates, "install_requirements", lambda: None)
    assert updates.run_update(release, "1.1.0", app_pid=0, restart=False)["ok"]
    assert updates.current_version() == "1.1.0" and text(here, ".env") == USER_DATA[".env"]


def test_the_download_is_checked_before_anything_changes(tmp_path):
    def archive(name, files):
        path = tmp_path / name
        with zipfile.ZipFile(path, "w") as z:
            for rel, content in files.items():
                z.writestr(rel, content)
        return path
    top = "aearm-gte-bookings-assistant-1a2b3c/"
    root = updates.unpack(archive("v1.1.0.zip", {top + "app.py": "x", top + "VERSION": "1.1.0\n"}), "1.1.0")
    assert root.name == top.strip("/") and (root / "app.py").exists()
    with pytest.raises(RuntimeError, match="VERSION file says 1.0.9"):
        updates.unpack(archive("v1.2.0.zip", {top + "app.py": "x", top + "VERSION": "1.0.9"}), "1.2.0")
    with pytest.raises(RuntimeError, match="unsafe path"):
        updates.unpack(archive("bad.zip", {"../evil.py": "x"}), "1.1.0")
    with pytest.raises(RuntimeError, match="doesn't look like this app"):
        updates.unpack(archive("other.zip", {top + "README.md": "x"}), "1.1.0")


def test_latest_release_from_github(install, monkeypatch):
    answer = {"tag_name": "v1.1.0", "published_at": "2026-10-20T09:30:00Z", "body": "Faster dashboards.",
              "zipball_url": "https://api.github.com/zip", "html_url": "https://github.com/release"}
    monkeypatch.setattr(updates, "_get", lambda url, timeout=20: io.BytesIO(json.dumps(answer).encode()))
    release = updates.latest_release()
    assert (release.version, release.published, release.notes) == ("1.1.0", "20 Oct 2026", "Faster dashboards.")
    assert release.is_newer()
    assert not updates.Release("1.0.0", "v1.0.0", "", "", "", "").is_newer()

    def none_yet(url, timeout=20):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
    monkeypatch.setattr(updates, "_get", none_yet)
    assert updates.latest_release() is None
