"""WATCH_VIDEO / WATCH_VIDEO_ON_MOBILE strategy.

Posts video progress timestamps on Discord's native player cadence
(7-9.5s ticks, six-decimal floats, small jitter), syncing local progress
with whatever the server reports back. Works entirely over REST.
"""

from __future__ import annotations

import random
import time

from .api import ApiError, DiscordAPI
from .models import Quest, Task

MAX_TASK_FAILURES = 5
MAX_TIME_SECONDS = 25 * 60


def run_video(api: DiscordAPI, quest: Quest, task: Task) -> bool:
    target = task.target if task.target > 0 else 300.0
    current = quest.progress_for(task.key)
    if current >= target:
        return True

    print(f"    [i] watching video: {current:.1f}s / {target:.0f}s done, ~{int(target - current)}s left")
    failures = 0
    started = time.monotonic()
    completed_key = None

    while current < target:
        if time.monotonic() - started > MAX_TIME_SECONDS:
            print("    [!] 25-minute cap reached, giving up on this video")
            return False

        delay = random.uniform(7.0, 9.5)
        time.sleep(delay)
        current += delay + random.uniform(-0.01, 0.01)
        timestamp = round(min(target, current), 6)

        try:
            response = api.video_progress(quest.id, timestamp)
        except ApiError as err:
            if err.skippable:
                print(f"    [!] quest rejected progress ({err.message}), skipping")
                return False
            failures += 1
            print(f"    [!] video progress failed ({failures}/{MAX_TASK_FAILURES}): {err.message}")
            if failures >= MAX_TASK_FAILURES:
                return False
            continue
        failures = 0

        progress = (response or {}).get("progress") or {}
        for key in (task.key, "WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE"):
            entry = progress.get(key)
            if isinstance(entry, dict) and entry.get("value") is not None:
                completed_key = key
                server_value = float(entry["value"])
                if server_value > current:
                    current = min(target, server_value)
                break
        if (response or {}).get("completed_at"):
            print("    [+] server marked the video complete")
            return True
        print(f"        {min(current, target):.1f}s / {target:.0f}s")

    # Target reached locally; give the server a moment to confirm.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        time.sleep(5)
        response = api.video_progress(quest.id, timestamp)
        if (response or {}).get("completed_at"):
            print("    [+] video quest complete")
            return True
        progress = (response or {}).get("progress") or {}
        for key in (completed_key, task.key, "WATCH_VIDEO"):
            entry = progress.get(key)
            if isinstance(entry, dict):
                if float(entry.get("value", 0)) >= target:
                    print("    [+] video quest complete")
                    return True
                break
    print("    [+] sent the full watch time (check progress in Discord if unsure)")
    return True
