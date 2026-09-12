"""PLAY_ON_DESKTOP strategy.

Two ways to make Discord credit play time:

- "rest" mode: POST /quests/{id}/heartbeat with the game's application_id
  every ~60 seconds until the server reports the quest complete. Works
  anywhere (GitHub Actions, Android users via CI) but the heartbeats are
  forged - Discord's server can tell no client ever detected a game process.
- "client" mode: launch a dummy executable named exactly like the quest
  game's real binary; the Discord desktop client detects the process and
  sends the heartbeats itself, from your real IP with real client
  telemetry. Structurally the safer path, but it needs the desktop client
  running on this machine.

"auto" picks client mode when Discord.exe is running locally (and the task
is not a console task), rest mode otherwise.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from . import stub
from .api import ApiError, DiscordAPI
from .models import CONSOLE_ONLY_KEYS, Quest, Task

HEARTBEAT_INTERVAL = (55.0, 65.0)
NO_PROGRESS_BEATS = 10
MAX_TIME_SECONDS = 25 * 60
ACTIVITY_STREAM_KEY = "call:1:1"


def _status_progress(status: dict | None, key: str) -> float:
    entry = (status or {}).get("progress", {}).get(key)
    if isinstance(entry, dict) and entry.get("value") is not None:
        return float(entry["value"])
    return -1.0


def run_game_rest(api: DiscordAPI, quest: Quest, task: Task) -> bool:
    if not task.app_id:
        print("    [!] no application id on this quest, cannot heartbeat")
        return False

    target = task.target if task.target > 0 else 900.0
    print(f"    [i] heartbeat mode: claiming play time for application {task.app_id}")
    print(f"        target {target:.0f}s, beating every ~60s like the real client")

    started = time.monotonic()
    last_progress = quest.progress_for(task.key)
    zero_beats = 0
    failures = 0

    while True:
        elapsed = time.monotonic() - started
        if elapsed > MAX_TIME_SECONDS:
            print("    [!] 25-minute cap reached, stopping")
            return False

        try:
            status = api.heartbeat(quest.id, task.app_id, terminal=False)
        except ApiError as err:
            if err.skippable:
                print(f"    [!] quest rejected heartbeats ({err.message}), skipping")
                return False
            failures += 1
            print(f"    [!] heartbeat failed ({failures}): {err.message}")
            if failures >= 5:
                return False
            time.sleep(random.uniform(20.0, 40.0))
            continue
        failures = 0

        if (status or {}).get("completed_at"):
            print("    [+] server marked the quest complete")
            _send_terminal(api, quest.id, task.app_id)
            return True

        progress = _status_progress(status, task.key)
        if progress >= 0 and progress >= target:
            print(f"    [+] progress {progress:.0f}s reached target {target:.0f}s")
            _send_terminal(api, quest.id, task.app_id)
            return True

        if progress > last_progress:
            zero_beats = 0
            print(f"        {progress:.0f}s / {target:.0f}s credited")
            last_progress = progress
        else:
            zero_beats += 1
            if zero_beats >= NO_PROGRESS_BEATS and elapsed > NO_PROGRESS_BEATS * 60:
                print("    [!] Discord is not crediting these heartbeats (10 beats,")
                print("        no progress). It may be rejecting forged play time;")
                print("        try the desktop-client mode locally instead.")
                return False

        time.sleep(random.uniform(*HEARTBEAT_INTERVAL))


def _send_terminal(api: DiscordAPI, quest_id: str, app_id: str) -> None:
    try:
        api.heartbeat(quest_id, app_id, terminal=True)
    except ApiError:
        pass


def run_activity(api: DiscordAPI, quest: Quest, task: Task) -> bool:
    """PLAY_ACTIVITY via a stream-key heartbeat. Experimental: Discord's
    activity backend validates heartbeats and often answers 403."""
    target = task.target if task.target > 0 else 900.0
    print(f"    [i] experimental activity mode, stream key {ACTIVITY_STREAM_KEY}")
    started = time.monotonic()
    failures = 0
    while True:
        if time.monotonic() - started > MAX_TIME_SECONDS:
            print("    [!] 25-minute cap reached, stopping")
            return False
        try:
            status = api.heartbeat_stream(quest.id, ACTIVITY_STREAM_KEY, terminal=False)
        except ApiError as err:
            if err.skippable:
                print(f"    [!] activity heartbeats rejected ({err.message})")
                print("        (expected on non-video activity quests - the backend")
                print("        validates them; only desktop play really counts)")
                return False
            failures += 1
            if failures >= 5:
                return False
            time.sleep(random.uniform(20.0, 40.0))
            continue
        if (status or {}).get("completed_at"):
            try:
                api.heartbeat_stream(quest.id, ACTIVITY_STREAM_KEY, terminal=True)
            except ApiError:
                pass
            print("    [+] activity quest complete")
            return True
        progress = _status_progress(status, task.key)
        if progress >= 0:
            print(f"        {progress:.0f}s / {target:.0f}s")
        time.sleep(random.uniform(*HEARTBEAT_INTERVAL))


def _find_progress(api: DiscordAPI, quest_id: str, key: str) -> float:
    payload = api.get_quests()
    quests = payload
    if isinstance(payload, dict):
        quests = payload.get("quests") or payload.get("items") or []
    for raw in quests or []:
        if isinstance(raw, dict) and str(raw.get("id")) == quest_id:
            progress = ((raw.get("user_status") or {}).get("progress")) or {}
            entry = progress.get(key) or progress.get("PLAY_ON_DESKTOP")
            if isinstance(entry, dict) and entry.get("value") is not None:
                return float(entry["value"])
    return -1.0


def run_game_client(api: DiscordAPI, quest: Quest, task: Task, games_dir: Path) -> bool:
    if not task.app_id:
        print("    [!] no application id on this quest, cannot fake the game")
        return False

    if not stub.discord_running():
        print("    [!] Discord.exe does not appear to be running - the desktop client")
        print("        must be open for it to detect the fake game process. Start it first")
        print("        or use --game-mode rest.")
        return False

    print(f"    [i] fetching game metadata for application {task.app_id}")
    try:
        app = api.application_public(task.app_id)
    except ApiError as err:
        print(f"    [!] could not fetch game metadata: {err.message}")
        return False
    if not app:
        print("    [!] Discord returned no application data for this game")
        return False

    exe_name, game_name = stub.game_executable(app)
    print(f"    [i] game: {game_name} (fake process: {exe_name})")

    target = task.target if task.target > 0 else 900.0
    baseline = quest.progress_for(task.key)
    print(f"    [i] play target: {target:.0f}s, already credited: {baseline:.0f}s")

    exe_path, stub_kind = stub.prepare_stub(games_dir, task.app_id, exe_name)
    duration = int(target - baseline) + 120
    proc = stub.launch_stub(exe_path, stub_kind, duration)
    print(f"    [i] launched {exe_path} for ~{duration}s - waiting for Discord to notice it")

    started = time.monotonic()
    last_progress = baseline
    stalled_polls = 0
    ok = False
    try:
        while True:
            elapsed = time.monotonic() - started
            if elapsed > MAX_TIME_SECONDS:
                print("    [!] 25-minute cap reached, stopping")
                break
            if proc.poll() is not None:
                print("    [!] stub process exited early")
                break

            time.sleep(random.uniform(55.0, 65.0))
            try:
                progress = _find_progress(api, quest.id, task.key)
            except ApiError as err:
                print(f"    [!] progress poll failed: {err.message}")
                stalled_polls += 1
                if elapsed > 120 and stalled_polls >= NO_PROGRESS_BEATS:
                    print("    [!] giving up after repeated progress-poll failures")
                    break
                continue

            if progress < 0:
                continue

            if progress > last_progress:
                stalled_polls = 0
                print(f"        {progress:.0f}s / {target:.0f}s credited")
                if progress >= target:
                    ok = True
                    break
            else:
                stalled_polls += 1
                if elapsed > 120 and stalled_polls >= NO_PROGRESS_BEATS:
                    print("    [!] Discord is not crediting play time for the fake process.")
                    print("        Checks: is the quest visible in your Quests page? Is the game")
                    print("        listed under Settings > Registered Games? Try joining the quest")
                    print("        in Discord, then rerun AppleQuest.")
                    break
    finally:
        stub.stop(proc)

    stub.cleanup_leftovers(games_dir)
    return ok


def run_game(api: DiscordAPI, quest: Quest, task: Task, games_dir: Path, mode: str = "auto") -> bool:
    if mode == "auto":
        mode = "client" if stub.discord_running() and task.key not in CONSOLE_ONLY_KEYS else "rest"
    if mode == "client" and task.key in CONSOLE_ONLY_KEYS:
        print("    [i] console task: no desktop process to fake, using heartbeats")
        mode = "rest"
    if mode == "client":
        return run_game_client(api, quest, task, games_dir)
    return run_game_rest(api, quest, task)
