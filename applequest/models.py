"""Quest models and parsing.

The quest payloads come from GET /quests/@me. Field names over raw REST are
snake_case, but some payloads carry camelCase keys depending on where Discord's
client transforms them, so every accessor is defensive about both.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Console task keys. They are completed with the same REST heartbeat as
# PLAY_ON_DESKTOP (the body is identical), but they can never use the local
# dummy-exe mode because there is no Windows process to fake for them.
CONSOLE_ONLY_KEYS = {"PLAY_ON_XBOX", "PLAY_ON_PLAYSTATION"}

# Task type routing. Exact matches first, then prefixes, mirroring how
# Discord's own client groups quest task keys.
TYPE_MAP: list[tuple[str, str]] = [
    ("ACHIEVEMENT_IN_ACTIVITY", "ACHIEVEMENT_ACTIVITY"),
    ("PLAY_ACTIVITY", "ACTIVITY"),
    ("ACHIEVEMENT_IN_GAME", "ACHIEVEMENT_GAME"),
]

TASK_GROUP_ORDER = ["VIDEO", "GAME", "STREAM", "ACTIVITY", "ACHIEVEMENT_ACTIVITY", "ACHIEVEMENT_GAME"]


def _get(obj: Any, *paths: str, default: Any = None) -> Any:
    for path in paths:
        cur = obj
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.lstrip("-").isdigit():
                index = int(part)
                if -len(cur) <= index < len(cur):
                    cur = cur[index]
                else:
                    ok = False
                    break
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return default


def classify_task(key: str) -> str:
    for exact, group in TYPE_MAP:
        if key == exact:
            return group
    if "VIDEO" in key:
        return "VIDEO"
    if key.startswith("PLAY"):
        return "GAME"
    if key.startswith("STREAM"):
        return "STREAM"
    if "ACTIVITY" in key:
        return "ACTIVITY"
    return "UNKNOWN"


@dataclass
class Task:
    key: str
    group: str
    app_id: str | None
    target: float
    supported: bool
    reason: str = ""

    @property
    def supported_group(self) -> str:
        """Groups AppleQuest can drive standalone."""
        return self.group in ("VIDEO", "GAME")


@dataclass
class Quest:
    id: str
    name: str
    reward: str
    expires_at: float | None
    enrolled: bool
    completed: bool
    claimed: bool
    tasks: list[Task] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at < time.time() * 1000

    def progress_for(self, key: str) -> float:
        entry = _get(self.raw, f"user_status.progress.{key}", f"userStatus.progress.{key}")
        if isinstance(entry, dict):
            return float(entry.get("value", 0) or 0)
        if isinstance(entry, (int, float)):
            return float(entry)
        fallback = _get(self.raw, "user_status.stream_progress_seconds", "userStatus.streamProgressSeconds")
        return float(fallback or 0)

    @property
    def sealed_blob(self) -> str | None:
        blob = _get(
            self.raw,
            "traffic_metadata_sealed",
            "trafficMetadataSealed",
            "user_status.traffic_metadata_sealed",
            "config.traffic_metadata_sealed",
        )
        return blob if isinstance(blob, str) else None

    @property
    def raw_blob(self) -> str | None:
        blob = _get(self.raw, "traffic_metadata_raw", "trafficMetadataRaw")
        return blob if isinstance(blob, str) else None

    @property
    def mobile_video_only(self) -> bool:
        """Quests whose only video task is the mobile one need to be enrolled
        from an Android identity (location 12) for progress to count."""
        keys = {task.key for task in self.tasks}
        return "WATCH_VIDEO_ON_MOBILE" in keys and "WATCH_VIDEO" not in keys

    def best_task(self) -> Task | None:
        """Pick the most completable task, mirroring Orion's preference:
        VIDEO (deterministic over REST) beats GAME (needs the desktop client
        to notice a fake process). Stream never works; the rest can't be
        driven at all."""
        ranked = sorted(self.tasks, key=lambda t: TASK_GROUP_ORDER.index(t.group) if t.group in TASK_GROUP_ORDER else 99)
        unsupported_only = True
        for task in ranked:
            if task.group == "VIDEO" and "MOBILE" not in task.key:
                return task
            if task.group == "VIDEO" and "MOBILE" in task.key:
                # Video-on-mobile tasks are the same REST endpoint; they work too.
                return task
            if task.group == "GAME" and unsupported_only:
                return task
        return ranked[0] if ranked else None

    def summary_line(self) -> str:
        flags = []
        if self.expired:
            flags.append("EXPIRED")
        if self.claimed:
            flags.append("CLAIMED")
        elif self.completed:
            flags.append("DONE-UNCLAIMED")
        elif self.enrolled:
            flags.append("ENROLLED")
        task = self.best_task()
        if task:
            if task.supported_group:
                flags.append(task.group)
            else:
                flags.append(f"{task.group}:UNSUPPORTED")
        tag = f" [{', '.join(flags)}]" if flags else ""
        return f"{self.name} -> {self.reward}{tag}"


def _parse_task(key: str, spec: dict, legacy_app_id: str | None) -> Task:
    group = classify_task(key)
    app_id = _get(spec, "applications.0.id")
    if not app_id:
        app_id = legacy_app_id
    target = _get(spec, "target", default=0)
    try:
        target = float(target or 0)
    except (TypeError, ValueError):
        target = 0.0

    task = Task(key=key, group=group, app_id=app_id, target=target, supported=True)
    if group == "STREAM":
        task.supported = False
        task.reason = (
            "Discord verifies a real Go Live stream plus a second person in the voice "
            "channel before counting stream progress; no tool can fake this"
        )
    elif group == "ACTIVITY":
        task.supported = False
        task.reason = (
            "activity quest: Discord's activity backend validates heartbeats, so this "
            "needs the experimental stream-key path (see --experimental-activity)"
        )
    elif group.startswith("ACHIEVEMENT"):
        task.supported = False
        task.reason = (
            "achievement quest: in-game ones are impossible, in-activity ones require an "
            "OAuth forgery chain Discord is actively enforcing against"
        )
    return task


def parse_quest(raw: dict) -> Quest:
    config = _get(raw, "config", default={}) or {}
    user_status = _get(raw, "user_status", "userStatus", default={}) or {}

    legacy_app_id = _get(config, "application.id", "applicationId")

    task_specs: dict[str, Any] = {}
    for path in ("taskConfigV2.tasks", "taskConfig.tasks", "taskConfigV2", "taskConfig"):
        tasks = _get(config, path)
        if isinstance(tasks, dict) and tasks:
            task_specs = tasks
            break
    # Older payloads sometimes inline the single task at the top of the config.
    if not task_specs:
        tasks = _get(config, "tasks")
        if isinstance(tasks, dict) and tasks:
            task_specs = tasks

    tasks = []
    for key, spec in task_specs.items():
        if isinstance(spec, dict):
            tasks.append(_parse_task(key, spec, legacy_app_id))

    expires_at = _get(config, "expires_at", "expiresAt")
    if isinstance(expires_at, str):
        try:
            from datetime import datetime

            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp() * 1000
        except ValueError:
            expires_at = None

    rewards = _get(config, "rewards_config.rewards", "rewardsConfig.rewards", default=[]) or []
    reward_name = _get(rewards[0], "messages.name", "name", default="a reward") if rewards else "a reward"

    return Quest(
        id=str(_get(raw, "id", default="")),
        name=str(_get(config, "messages.quest_name", "messages.questName", default=raw.get("id", "Unnamed quest"))),
        reward=str(reward_name),
        expires_at=float(expires_at) if isinstance(expires_at, (int, float)) else None,
        enrolled=bool(_get(user_status, "enrolled_at", "enrolledAt")),
        completed=bool(_get(user_status, "completed_at", "completedAt")),
        claimed=bool(_get(user_status, "claimed_at", "claimedAt")),
        tasks=tasks,
        raw=raw,
    )


def find_account_blocks(payload: Any) -> tuple[str | None, str | None]:
    """Look for Discord's enforcement signals: enrollment blocked / access
    suspended. They may sit at the response root or per quest."""
    roots = []
    if isinstance(payload, dict):
        roots.append(payload)
    elif isinstance(payload, list):
        roots.extend(q for q in payload if isinstance(q, dict))

    enrollment_blocked = None
    access_suspended = None
    for root in roots:
        for key in ("quest_enrollment_blocked_until", "questEnrollmentBlockedUntil"):
            value = root.get(key)
            if value:
                enrollment_blocked = str(value)
        us = root.get("user_status") or root.get("userStatus")
        if isinstance(us, dict):
            for key in ("quest_access_suspended_until", "questAccessSuspendedUntil"):
                value = us.get(key)
                if value:
                    access_suspended = str(value)
    return enrollment_blocked, access_suspended
