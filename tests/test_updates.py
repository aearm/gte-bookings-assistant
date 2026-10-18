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
    web = {top + "app.py": "x", top + "VERSION": "2.0.0", top + "web/package.json": "{}"}
    with pytest.raises(RuntimeError, match="still being built"):  # GitHub's source zip: no built web app yet
        updates.unpack(archive("v2.0.0-src.zip", web), "2.0.0")
    full = updates.unpack(archive("v2.0.0.zip", {**web, top + "web/dist/index.html": "<html>"}), "2.0.0")
    assert (full / "web" / "dist" / "index.html").exists()


def test_latest_release_from_github(install, monkeypatch):
    answer = {"tag_name": "v1.1.0", "published_at": "2026-10-20T09:30:00Z", "body": "Faster dashboards.",
              "zipball_url": "https://api.github.com/zip", "html_url": "https://github.com/release"}
    monkeypatch.setattr(updates, "_get", lambda url, timeout=20: io.BytesIO(json.dumps(answer).encode()))
    release = updates.latest_release()
    assert (release.version, release.published, release.notes) == ("1.1.0", "20 Oct 2026", "Faster dashboards.")
    assert release.is_newer()
    assert not updates.Release("1.0.0", "v1.0.0", "", "", "", "").is_newer()
    assert release.zip_url == "https://api.github.com/zip"  # no built package attached: the source zip
    answer["assets"] = [{"name": "bookings-assistant-1.1.0.zip", "browser_download_url": "https://github.com/full.zip"}]
    assert updates.latest_release().zip_url == "https://github.com/full.zip"  # the package with the web app

    def none_yet(url, timeout=20):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
    monkeypatch.setattr(updates, "_get", none_yet)
    assert updates.latest_release() is None


def test_the_app_comes_back_as_the_server_that_was_running(monkeypatch):
    """Without a Windows task, the updater starts again the script that ran the app: the web app
    (start_api.py) or the previous one (start_server.py); never anything else."""
    started = []
    monkeypatch.setattr(updates, "_task_exists", lambda: False)
    monkeypatch.setattr(updates.subprocess, "Popen", lambda args, **kw: started.append(args[-1]))
    updates.start_app("start_api.py")
    updates.start_app()
    updates.start_app("rm -rf.py")
    assert [name.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for name in started] == \
        ["start_api.py", "start_server.py", "start_server.py"]


@pytest.mark.skipif(updates.os.name != "nt", reason="Windows process list")
def test_stopping_the_app_finds_the_processes_it_started():
    """The web server's cube workers are its child processes; they are stopped with it, or they would keep
    the app's files open while the update replaces them."""
    import subprocess
    import sys
    import time
    grandchild = "import time; time.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", f"import subprocess, sys, time; "
                              f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); time.sleep(60)"])
    try:
        found = []
        for _ in range(40):  # the grandchild needs a moment to start
            found = updates.descendants(child.pid)
            if found:
                break
            time.sleep(0.25)
        assert found and child.pid not in found
        assert child.pid in updates.descendants(updates.os.getpid())
        updates._kill(child.pid)  # ends that process only (never a Ctrl+Break to the whole console)
        assert child.wait(10) == 9 and not updates._alive(child.pid)
    finally:
        for pid in found:
            updates._kill(pid)
        child.kill()


def test_the_shortcut_starts_the_task_only_when_it_runs_the_web_app(tmp_path, monkeypatch):
    """start_api.py --open starts the Windows task when it runs this copy's web app; a task set up for the
    previous app (or none) would never answer on the web app's port, so the server starts there instead."""
    import start_api
    monkeypatch.setattr(start_api, "BASE", tmp_path)
    assert start_api.task_from_settings() == ""  # no autostart.json: set up before, or not at all
    (tmp_path / "data").mkdir()
    saved = tmp_path / "data" / "autostart.json"
    saved.write_text('{"task": "Bookings Assistant test", "port": 8640, "app": "web"}', encoding="utf-8-sig")
    assert start_api.task_from_settings() == "Bookings Assistant test"
    saved.write_text('{"task": "Bookings Assistant", "port": 8501, "app": "classic"}', encoding="utf-8")
    assert start_api.task_from_settings() == ""
