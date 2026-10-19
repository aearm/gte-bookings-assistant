"""Updating the app from its GitHub releases, keeping everything that belongs to this installation.

An admin checks for a new version in Settings (App version). Update downloads the release, and a
helper - this file, run as its own process - stops the app, puts the new code in place, installs any
new libraries, and starts the app again. The page reconnects by itself.

Kept exactly as they are: settings and keys (.env, Windows Credential Manager), dashboards, the data
layer and value lists (models/), answer memory, usage, results and history (data/), the glossary
and saved queries, and the Python environment (.venv). Before anything changes the current code is
saved in data/backup/; if a step fails, the previous version is put back and started.

A developer copy (a git clone) is updated with git pull instead.

Releasing a version: put the number in VERSION (e.g. 2.0.1) and what changed in CHANGELOG.md (admins see
that text), commit and push to main. GitHub then publishes the release by itself (.github/workflows/release.yml).

Helper:  python updates.py apply <unpacked release folder> <version> <app process id> [start_api.py]"""
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from packaging.version import InvalidVersion, Version

BASE = Path(__file__).resolve().parent
REPO = os.getenv("UPDATE_REPO", "aearm/gte-bookings-assistant")  # owner/name on GitHub
TASK = "Bookings Assistant"  # the Windows task that starts the app (install/install_autostart.ps1)


def task_name() -> str:
    """The Windows task that starts this copy of the app: install/install_autostart.ps1 notes it in
    data/autostart.json (another copy on the same computer has a task of its own)."""
    try:
        return json.loads((BASE / "data" / "autostart.json").read_text(encoding="utf-8-sig"))["task"] or TASK
    except (OSError, ValueError, KeyError, TypeError):
        return TASK

# What an update never replaces or removes. Release files under ADD_ONLY are added when missing
# (e.g. a new sample file), never written over.
KEEP_FILES = {".env", "dashboards.json", "dashboard.json", "dashboard.json.bak", "schema.md", "schema_local.md",
              "business_notes.md", "glossary.json"}
KEEP_DIRS = {".venv", ".git", "adomd", "models", ".claude", "__pycache__"}
ADD_ONLY = {"data", "queries"}
# Files that were in the app folder before and are gone from the releases (removed by an update even
# when the installation has no list of the files the last update put there, e.g. installed from a zip)
RETIRED = {"setup.bat", "autostart.bat", "setup_windows.ps1", "install_autostart.ps1", "run_app.bat", "setup.sh",
           "run_app.sh"}


def _data() -> Path:
    return BASE / "data"


def status_file() -> Path:
    return _data() / "update_status.json"


def manifest_file() -> Path:
    """The code files the last update installed (so files a release drops can be removed)."""
    return _data() / "installed_files.json"


def lock_file() -> Path:
    return _data() / "updates" / "updating.lock"


# ---------------------------------------------------------------- versions --

def current_version() -> str:
    try:
        return (BASE / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _version(text: str) -> Version:
    try:
        return Version(text.strip().lstrip("vV"))
    except InvalidVersion:
        return Version("0")


def is_developer_copy() -> bool:
    return (BASE / ".git").exists()


@dataclass
class Release:
    version: str
    tag: str
    published: str   # "20 Oct 2026"
    notes: str
    zip_url: str
    page: str

    def is_newer(self) -> bool:
        return _version(self.version) > _version(current_version())


def _get(url: str, timeout: int = 20):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "bookings-assistant-updater"})
    return urllib.request.urlopen(request, timeout=timeout)


def latest_release() -> Release | None:
    """The newest published release on GitHub, or None if there is none yet."""
    try:
        with _get(f"https://api.github.com/repos/{REPO}/releases/latest") as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(f"GitHub answered {exc.code} when asked for the latest version.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Couldn't reach GitHub to check for updates ({exc.reason}).") from exc
    published = data.get("published_at") or ""
    try:
        published = datetime.fromisoformat(published.replace("Z", "+00:00")).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        pass
    tag = data.get("tag_name", "")
    # the full app (with the built React app, web/dist) is attached to each release by GitHub Actions
    # (.github/workflows/release.yml); GitHub's own source zip is the fallback for older releases
    full = next((a.get("browser_download_url", "") for a in data.get("assets") or []
                 if str(a.get("name", "")).startswith("bookings-assistant-") and str(a.get("name", "")).endswith(".zip")), "")
    return Release(version=tag.lstrip("vV"), tag=tag, published=published, notes=(data.get("body") or "").strip(),
                   zip_url=full or data.get("zipball_url", ""), page=data.get("html_url", ""))


# ---------------------------------------------------------------- download --

def download(release: Release) -> Path:
    """The release's files, unpacked into data/updates/<tag>/ and checked. Returns that folder."""
    folder = _data() / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"{release.tag}.zip"
    with _get(release.zip_url, timeout=120) as response, open(archive, "wb") as out:
        shutil.copyfileobj(response, out)
    return unpack(archive, release.version)


def unpack(archive: Path, version: str) -> Path:
    """Unpack a release zip (GitHub puts everything in one top folder) and check it is the app, at
    the version it claims to be."""
    target = archive.with_suffix("")
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            parts = Path(name).parts
            if name.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
                raise RuntimeError(f"The download contains an unsafe path ({name}); nothing was changed.")
        z.extractall(target)
    tops = [p for p in target.iterdir()]
    root = tops[0] if len(tops) == 1 and tops[0].is_dir() else target
    if not (root / "app.py").exists() or not (root / "VERSION").exists():
        raise RuntimeError("The download doesn't look like this app (no app.py or VERSION); nothing was changed.")
    if (root / "web" / "package.json").exists() and not (root / "web" / "dist" / "index.html").exists():
        raise RuntimeError("This release's web app is still being built on GitHub; try again in a few minutes. "
                           "Nothing was changed.")
    found = (root / "VERSION").read_text(encoding="utf-8").strip()
    if _version(found) != _version(version):
        raise RuntimeError(f"The release is tagged {version} but its VERSION file says {found}; nothing was changed.")
    return root


# ---------------------------------------------------------------- putting the new code in place --

def _kind(rel: str) -> str:
    """'keep' (never touched), 'add' (added if missing) or 'code' (replaced by the release)."""
    parts = rel.split("/")
    if rel in KEEP_FILES or parts[0] in KEEP_DIRS or "__pycache__" in parts:
        return "keep"
    return "add" if parts[0] in ADD_ONLY else "code"


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def plan(new_root: Path) -> dict:
    """What an update to new_root changes here: files to write (new or different), and code files
    the last update installed that this release no longer has (to remove)."""
    new = _files(new_root)
    write = [rel for rel in new if (_kind(rel) == "code" and _digest(BASE / rel) != _digest(new_root / rel))
             or (_kind(rel) == "add" and not (BASE / rel).exists())]
    try:
        before = json.loads(manifest_file().read_text(encoding="utf-8")).get("files", [])
    except (OSError, ValueError):
        before = []
    remove = [rel for rel in sorted(set(before) | RETIRED)
              if rel not in new and _kind(rel) == "code" and (BASE / rel).exists()]
    return {"write": write, "remove": remove, "code": [rel for rel in new if _kind(rel) == "code"]}


def apply(new_root: Path, version: str) -> dict:
    """Put the release's code in place. Saves what it replaces or removes first (data/backup/), and
    returns what it did - enough to undo it (rollback)."""
    steps = plan(new_root)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = _data() / "backup" / f"app-{current_version()}-{stamp}.zip"
    backup.parent.mkdir(parents=True, exist_ok=True)
    existing = [rel for rel in steps["write"] + steps["remove"] if (BASE / rel).exists()]
    with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in existing:
            z.write(BASE / rel, rel)
        if manifest_file().exists():
            z.write(manifest_file(), manifest_file().relative_to(BASE).as_posix())
    done = {"backup": str(backup), "added": [rel for rel in steps["write"] if not (BASE / rel).exists()],
            "written": steps["write"], "removed": steps["remove"],
            "requirements": _digest(BASE / "requirements.txt") != _digest(new_root / "requirements.txt")}
    try:
        for rel in steps["write"]:
            (BASE / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(new_root / rel, BASE / rel)
        for rel in steps["remove"]:
            (BASE / rel).unlink(missing_ok=True)
        manifest_file().write_text(json.dumps({"version": version, "files": steps["code"]}, indent=1),
                                   encoding="utf-8")
    except Exception:
        rollback(done)
        raise
    return done


def rollback(done: dict) -> None:
    """Undo apply(): remove what it added and restore what it replaced or removed."""
    for rel in done.get("added", []):
        (BASE / rel).unlink(missing_ok=True)
    with zipfile.ZipFile(done["backup"]) as z:
        names = set(z.namelist())
        z.extractall(BASE)
    if manifest_file().relative_to(BASE).as_posix() not in names:
        manifest_file().unlink(missing_ok=True)


def install_requirements() -> None:
    python = Path(sys.executable)
    console = python.with_name("python.exe") if python.name.lower() == "pythonw.exe" else python
    result = subprocess.run([str(console if console.exists() else python), "-m", "pip", "install", "-r",
                             str(BASE / "requirements.txt"), "--quiet", "--disable-pip-version-check"],
                            capture_output=True, text=True, timeout=1800, cwd=BASE)
    if result.returncode != 0:
        raise RuntimeError("Installing the new libraries failed: " + (result.stderr or result.stdout)[-1500:])


# ---------------------------------------------------------------- stopping and starting the app --

def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = ctypes.c_void_p
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
    k32.CloseHandle(ctypes.c_void_p(handle))
    return code.value == 259  # STILL_ACTIVE


def _kill(pid: int) -> None:
    """End a process at once. (On Windows signal 1 would be Ctrl+Break, sent to every process on the
    console; any other number ends the process itself.)"""
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def _task_exists() -> bool:
    return os.name == "nt" and subprocess.run(["schtasks", "/Query", "/TN", task_name()], capture_output=True).returncode == 0


def descendants(pid: int) -> list[int]:
    """The processes a process started, and theirs (the web server's cube workers), so they can be stopped
    with it: left running they would keep the app's files open."""
    if os.name != "nt" or pid <= 0:
        return []
    listed = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.ParentProcessId)\" }"],
                            capture_output=True, text=True, timeout=60)
    children: dict[int, list[int]] = {}
    for line in listed.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in found and child != pid:
                found.append(child)
                todo.append(child)
    return found


def stop_app(pid: int) -> None:
    """Stop the app (its Windows task, or the process) with the processes it started, and wait until it
    is gone."""
    helpers = descendants(pid)
    if _task_exists():
        subprocess.run(["schtasks", "/End", "/TN", task_name()], capture_output=True)
    for second in range(30):
        if not _alive(pid):
            break
        if second == 3:  # still running: end the process itself
            _kill(pid)
        time.sleep(1)
    else:
        raise RuntimeError("The app didn't stop, so nothing was changed.")
    for helper in helpers:
        if _alive(helper):
            _kill(helper)


SERVERS = ("start_api.py", "start_server.py")  # the web app, the previous (Streamlit) app


def start_app(server: str = "start_server.py") -> None:
    """Start the app again: its Windows task, or else `server` in the background."""
    if _task_exists():
        subprocess.run(["schtasks", "/Run", "/TN", task_name()], capture_output=True)
        return
    python = Path(sys.executable)
    background = python.with_name("pythonw.exe") if os.name == "nt" else python
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    script = server if server in SERVERS else "start_server.py"
    subprocess.Popen([str(background if background.exists() else python), str(BASE / script)], cwd=BASE,
                     creationflags=flags, start_new_session=os.name != "nt", close_fds=True)


def launch(new_root: Path, version: str, server: str = "start_server.py") -> None:
    """From the app: start the helper as a process of its own (outside the app's Windows task, so
    stopping the app doesn't stop it), which then stops the app and updates it. server: the script that
    runs this app, started again afterwards when there is no Windows task (start_api.py from the web app)."""
    lock_file().parent.mkdir(parents=True, exist_ok=True)
    lock_file().write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    python = Path(sys.executable)
    background = python.with_name("pythonw.exe") if os.name == "nt" else python
    args = [str(background if background.exists() else python), str(BASE / "updates.py"), "apply", str(new_root),
            version, str(os.getpid()), server]
    if os.name == "nt":  # created by Windows (WMI), not as a child of the app
        line = subprocess.list2cmdline(args).replace("'", "''")
        script = (f"$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
                  f"@{{CommandLine='{line}'; CurrentDirectory='{str(BASE).replace(chr(39), chr(39) * 2)}'}}; "
                  "exit $r.ReturnValue")
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            lock_file().unlink(missing_ok=True)
            raise RuntimeError("Couldn't start the updater: " + (result.stderr or result.stdout or "")[-500:])
    else:
        subprocess.Popen(args, cwd=BASE, start_new_session=True, close_fds=True)


def updating() -> bool:
    """An update is running (started less than 30 minutes ago)."""
    try:
        started = datetime.fromisoformat(lock_file().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return (datetime.now() - started).total_seconds() < 1800


def last_status() -> dict | None:
    try:
        return json.loads(status_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_update(new_root: Path, version: str, app_pid: int, restart: bool = True,
               server: str = "start_server.py") -> dict:
    """The helper's work: stop the app, update it (undone if a step fails), start it again."""
    status = {"time": datetime.now().isoformat(timespec="seconds"), "from": current_version(), "to": version,
              "ok": False, "error": ""}
    done = None
    try:
        if restart:
            stop_app(app_pid)
        done = apply(new_root, version)
        status["backup"] = done["backup"]
        if done["requirements"]:
            install_requirements()
        status["ok"] = True
    except Exception as exc:
        status["error"] = str(exc)[:2000]
        if done:
            try:
                rollback(done)
                status["error"] += " The previous version was put back."
            except Exception as again:
                status["error"] += f" Putting the previous version back also failed: {again}"
    finally:
        status_file().parent.mkdir(parents=True, exist_ok=True)
        status_file().write_text(json.dumps(status, indent=1), encoding="utf-8")
        lock_file().unlink(missing_ok=True)
        if restart:
            start_app(server)
    if status["ok"] and restart:
        connect_claude()
    return status


def connect_claude() -> None:
    """After an update of the main copy, Claude's connector and skill are brought up to date (install/connect_claude.py,
    as setup does: the skill Claude Code keeps is a copy). Never fails an update."""
    if task_name() != TASK:
        return
    try:
        subprocess.run([sys.executable, str(BASE / "install" / "connect_claude.py")], capture_output=True,
                       timeout=300, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


if __name__ == "__main__":
    if len(sys.argv) in (5, 6) and sys.argv[1] == "apply":
        run_update(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), server=(sys.argv[5:] or ["start_server.py"])[0])
    else:
        print(__doc__)
