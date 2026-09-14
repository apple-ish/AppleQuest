"""Dummy game executables for PLAY_ON_DESKTOP quests.

Discord's desktop client detects "detectable" games by scanning running
process image names against the executables it knows for each application.
AppleQuest copies a harmless, long-running Windows system binary to a file
named exactly like the quest game's real executable and runs it; Discord's
own client then believes the game is running and sends the quest heartbeats
itself. No client patching, no injected state.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000
# subprocess raises ValueError for creationflags on non-Windows platforms,
# which would crash the whole run on the Linux CI runner.
_SUBPROCESS_FLAGS = CREATE_NO_WINDOW if IS_WINDOWS else 0

STUB_SOURCES = [
    r"C:\Windows\System32\ping.exe",
    r"C:\Windows\System32\timeout.exe",
]


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _.-]", "", name).strip() or "game"


def find_stub_source() -> tuple[str, str]:
    """Return (path, kind) of the system binary to use as the stub body."""
    for source in STUB_SOURCES:
        if Path(source).is_file():
            kind = "ping" if "ping" in source.lower() else "timeout"
            return source, kind
    raise RuntimeError("no system stub binary found (expected ping.exe in System32)")


def game_executable(app: dict) -> tuple[str, str]:
    """Return (exe_name, game_dir_name) for a quest application."""
    name = sanitize(str(app.get("name") or "game"))
    executables = app.get("executables") or []
    exe_name = None
    for entry in executables:
        if entry.get("os") == "win32" and entry.get("name"):
            exe_name = str(entry["name"]).replace(">", "")
            break
    if not exe_name:
        for entry in executables:
            if entry.get("name"):
                exe_name = str(entry["name"]).replace(">", "")
                break
    if not exe_name:
        exe_name = f"{name}.exe"
    return sanitize(exe_name), name


def prepare_stub(games_dir: Path, app_id: str, exe_name: str) -> tuple[Path, str]:
    """Create the dummy executable, named after the game's real binary.

    Returns (path_to_dummy, stub_kind) so the launcher knows which system
    binary it is driving, whatever the dummy was renamed to.
    """
    target_dir = games_dir / app_id
    target_dir.mkdir(parents=True, exist_ok=True)
    exe_path = target_dir / exe_name
    kind_marker = target_dir / "stub.kind"
    if not exe_path.is_file():
        source, kind = find_stub_source()
        shutil.copyfile(source, exe_path)
        kind_marker.write_text(kind, encoding="utf-8")
        return exe_path, kind
    kind = kind_marker.read_text(encoding="utf-8").strip() if kind_marker.is_file() else "ping"
    return exe_path, kind


def launch_stub(exe_path: Path, kind: str, duration_seconds: int) -> subprocess.Popen:
    """Run the stub for at least duration_seconds. ping.exe sends one echo
    per second, so N pings stay alive for ~N seconds."""
    if kind == "ping":
        args = [str(exe_path), "-n", str(max(2, duration_seconds + 5)), "127.0.0.1"]
    else:
        args = [str(exe_path), "/t"]
    return subprocess.Popen(
        args,
        creationflags=_SUBPROCESS_FLAGS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def discord_running() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        output = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Discord.exe"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=_SUBPROCESS_FLAGS,
        ).stdout
        return "Discord.exe" in output
    except (OSError, subprocess.SubprocessError):
        return True


def stop(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass


def running_process_names() -> set[str]:
    if not IS_WINDOWS:
        return set()
    try:
        output = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=_SUBPROCESS_FLAGS,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    names = set()
    for line in output.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if parts and parts[0]:
            names.add(parts[0].lower())
    return names


def cleanup_leftovers(games_dir: Path) -> None:
    """Best-effort removal of stub folders whose processes are gone."""
    if not games_dir.is_dir():
        return
    running = running_process_names()
    for child in games_dir.iterdir():
        if not child.is_dir():
            continue
        if any(exe.name.lower() in running for exe in child.glob("*.exe")):
            continue
        shutil.rmtree(child, ignore_errors=True)
