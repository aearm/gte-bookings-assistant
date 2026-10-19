r"""Connects Bookings Assistant to Claude on this computer, so any Claude conversation can use the cubes' knowledge
and add or change the app's dashboards - with no Claude key of the app's (the conversation's own Claude does the
work, through the connector mcp_server.py and the bookings-dashboards skill).

- Claude Desktop: the connector in its settings (claude_desktop_config.json, the rest of it kept); quit and open
  Claude Desktop again to load it. Its chats get the drawing guide from the connector; the skill itself can be
  added too: Settings > Capabilities > Skills > upload data\bookings-dashboards-skill.zip.
- Claude Code: the connector for every project (claude mcp add --scope user) and the skill in
  %USERPROFILE%\.claude\skills\bookings-dashboards.

Setup (install\setup_windows.ps1) runs it when Claude is installed. By hand, in the app folder:
    .venv\Scripts\python.exe install\connect_claude.py            connect (again: brings it up to date)
    .venv\Scripts\python.exe install\connect_claude.py --remove   disconnect"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
NAME = "bookings-assistant"
SKILL = "bookings-dashboards"
MOVED = ".user-data-left"  # Claude Desktop left this folder for another one (its data lives elsewhere now)


def python() -> Path:
    for rel in (r".venv\Scripts\python.exe", ".venv/bin/python"):
        if (APP / rel).exists():
            return APP / rel
    return Path(sys.executable)


def server_entry() -> dict:
    return {"command": str(python()), "args": [str(APP / "mcp_server.py")]}


# ---------------------------------------------------------------- Claude Desktop --

def desktop_configs() -> list[Path]:
    """The settings files of the Claude Desktop installed here (none when it isn't)."""
    home, found = Path.home(), []
    local, roaming = Path(os.getenv("LOCALAPPDATA", home)), Path(os.getenv("APPDATA", home))
    found += sorted((local / "Claude-Data").glob("*/claude_desktop_config.json"))  # Microsoft Store version
    folders = [roaming / "Claude", home / "Library" / "Application Support" / "Claude"]
    folders += sorted((local / "Packages").glob("Claude_*/LocalCache/Roaming/Claude"))
    for folder in folders:
        if folder.is_dir() and not any(p.name.startswith(MOVED) for p in folder.iterdir()):
            found.append(folder / "claude_desktop_config.json")
    return list(dict.fromkeys(found))


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def connect_desktop(remove: bool) -> list[str]:
    lines = []
    for path in desktop_configs():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except ValueError:
            lines.append(f"Claude Desktop: {path} isn't valid JSON - left as it is.")
            continue
        servers = data.setdefault("mcpServers", {})
        if remove:
            if servers.pop(NAME, None) is None:
                continue
            if not servers:
                data.pop("mcpServers")
        elif servers.get(NAME) == server_entry():
            lines.append(f"Claude Desktop: already connected ({path}).")
            continue
        else:
            if path.exists():
                shutil.copy2(path, path.with_suffix(".json.before-bookings-assistant"))
            servers[NAME] = server_entry()
        _write_json(path, data)
        lines.append(f"Claude Desktop: {'disconnected' if remove else 'connected'} ({path}). Quit Claude Desktop "
                     "(also from the tray) and open it again to load it.")
    return lines or (["Claude Desktop: not installed here."] if not remove else [])


# ---------------------------------------------------------------- Claude Code --

def claude_cli() -> str:
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (Path.home() / ".local" / "bin" / "claude.exe", Path.home() / ".local" / "bin" / "claude"):
        if candidate.exists():
            return str(candidate)
    return ""


def _cli(cli: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([cli, *args], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)


def connect_code(remove: bool) -> list[str]:
    lines = []
    cli = claude_cli()
    if cli:
        _cli(cli, "mcp", "remove", "--scope", "user", NAME)  # (an older entry) - fine when there is none
        if not remove:
            entry = server_entry()
            done = _cli(cli, "mcp", "add", "--scope", "user", NAME, "--", entry["command"], *entry["args"])
            lines.append("Claude Code: connected for every project." if done.returncode == 0 else
                         f"Claude Code: not connected ({(done.stderr or done.stdout).strip()[:300]}).")
        else:
            lines.append("Claude Code: disconnected.")
    elif not remove and (Path.home() / ".claude").is_dir():
        lines.append("Claude Code: its command (claude) wasn't found, so the connector wasn't added; in a terminal: "
                     f'claude mcp add --scope user {NAME} -- "{python()}" "{APP / "mcp_server.py"}"')
    skills = Path.home() / ".claude" / "skills"
    target = skills / SKILL
    if remove:
        if (target / "SKILL.md").exists():
            shutil.rmtree(target)
            lines.append("Claude Code: skill removed.")
    elif skills.parent.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(APP / "skills" / SKILL, target)
        lines.append(f"Claude Code: skill {SKILL} installed ({target}).")
    return lines


# ---------------------------------------------------------------- the skill for Claude Desktop chats --

def skill_zip(remove: bool) -> list[str]:
    out = APP / "data" / f"{SKILL}-skill.zip"
    if remove:
        out.unlink(missing_ok=True)
        return []
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((APP / "skills" / SKILL).rglob("*")):
            if f.is_file():
                z.write(f, f"{SKILL}/{f.relative_to(APP / 'skills' / SKILL).as_posix()}")
    return [f"Skill for Claude Desktop chats (optional, the connector also hands Claude the guide): Settings > "
            f"Capabilities > Skills > upload {out}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Connect Bookings Assistant to Claude Desktop and Claude Code.")
    parser.add_argument("--remove", action="store_true", help="disconnect")
    args = parser.parse_args(argv)
    lines = connect_desktop(args.remove) + connect_code(args.remove) + skill_zip(args.remove)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
