"""Quest runner: list, select, enroll, complete, claim, notify.

Two faces:
- local (interactive): list quests, pick which to run, confirm claims
- CI (GitHub Actions, --ci or GITHUB_ACTIONS=true): headless, runs every
  eligible quest sequentially, notifies a webhook, never prompts
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

from .api import ApiError, DiscordAPI
from .game import run_activity, run_game
from .models import Quest, find_account_blocks, parse_quest
from .notify import quest_link, webhook_post
from .video import run_video

CLAIM_ASK = "ask"
CLAIM_AUTO = "auto"
CLAIM_NEVER = "never"


def _fmt_left(quest: Quest) -> str:
    if quest.expires_at is None:
        return "no expiry"
    delta = (quest.expires_at - time.time() * 1000) / 1000
    if delta <= 0:
        return "expired"
    hours = int(delta // 3600)
    minutes = int((delta % 3600) // 60)
    return f"{hours}h{minutes:02d}m left" if hours else f"{minutes}m left"


def fetch_quests(api: DiscordAPI) -> list[Quest]:
    payload = api.get_quests()
    if isinstance(payload, dict):
        items = payload.get("quests") or payload.get("items") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    return [parse_quest(raw) for raw in items if isinstance(raw, dict)]


def guard_account_state(payload: Any = None, api: DiscordAPI | None = None) -> None:
    if payload is None and api is not None:
        payload = api.get_quests()
    enrollment_blocked, access_suspended = find_account_blocks(payload)
    if access_suspended:
        raise SystemExit(
            f"[!] Discord has suspended quest access on this account until {access_suspended}.\n"
            "    That is an enforcement signal - do not keep automating quests on it."
        )
    if enrollment_blocked:
        raise SystemExit(
            f"[!] Discord has blocked new quest enrollment on this account until {enrollment_blocked}.\n"
            "    That is an enforcement signal - do not keep automating quests on it."
        )


def print_quests(quests: list[Quest]) -> None:
    if not quests:
        print("[i] no quests returned for this account")
        return
    for index, quest in enumerate(quests, start=1):
        print(f"  {index:>2}. {quest.summary_line()} ({_fmt_left(quest)})")


def ensure_enrolled(api: DiscordAPI, quest: Quest) -> bool:
    if quest.enrolled:
        return True
    mobile = quest.mobile_video_only
    print("    [i] enrolling (accepting the quest)" + (" from the Android identity" if mobile else "") + "...")
    try:
        api.enroll(quest.id, quest.sealed_blob, quest.raw_blob, mobile=mobile)
    except ApiError as err:
        if err.skippable:
            print(f"    [!] enrollment rejected ({err.message}) - skipping quest")
            return False
        print(f"    [!] enrollment failed: {err.message}")
        return False
    time.sleep(random.uniform(0.8, 1.5))
    return True


def try_claim(api: DiscordAPI, quest: Quest, claim_mode: str) -> None:
    if claim_mode == CLAIM_NEVER:
        print("    [i] reward left unclaimed - get it from the Quests page in Discord")
        return
    if claim_mode == CLAIM_ASK:
        answer = input(f"    claim reward for '{quest.name}' now? [y/N] ").strip().lower()
        if answer != "y":
            print("    [i] claim it later from the Quests page in Discord")
            return
    try:
        response = api.claim_reward(quest.id, quest.sealed_blob, quest.raw_blob)
    except ApiError as err:
        if err.captcha:
            print("    [!] Discord answered with a captcha challenge - claim it manually")
            print("        in the Discord app (Settings > Quests / Quests page)")
        else:
            print(f"    [!] claim failed: {err.message} - try the Quests page in Discord")
        return
    if response and response.get("claimed_at"):
        print(f"    [+] reward claimed: {quest.reward}")
    else:
        print("    [?] no confirmation in the response - check the Quests page in Discord")


def run_quest(
    api: DiscordAPI,
    quest: Quest,
    claim_mode: str,
    games_dir: Path,
    game_mode: str = "auto",
    experimental_activity: bool = False,
    notify_url: str | None = None,
) -> bool:
    print(f"\n== {quest.name} -> {quest.reward}")

    if quest.expired:
        print("    [!] expired, skipping")
        return False
    if quest.claimed:
        print("    [i] already claimed, nothing to do")
        return True
    if quest.completed:
        print("    [+] already complete - reward is waiting")
        try_claim(api, quest, claim_mode)
        return True

    task = quest.best_task()
    if task is None:
        print("    [!] no drivable task on this quest, skipping")
        return False
    if task.group == "ACTIVITY" and experimental_activity:
        pass
    elif not task.supported or not task.supported_group:
        print(f"    [!] cannot automate task {task.key}: {task.reason}")
        return False

    if not ensure_enrolled(api, quest):
        return False

    if task.group == "VIDEO":
        ok = run_video(api, quest, task)
    elif task.group == "GAME":
        ok = run_game(api, quest, task, games_dir, mode=game_mode)
    elif task.group == "ACTIVITY" and experimental_activity:
        ok = run_activity(api, quest, task)
    else:
        print(f"    [!] no strategy for task group {task.group}")
        return False

    if ok:
        print("    [+] quest complete")
        if notify_url:
            webhook_post(notify_url, f"Quest completed! {quest_link(quest.id, quest.name)}")
        try_claim(api, quest, claim_mode)
    return ok


def select_quests(quests: list[Quest]) -> list[Quest]:
    runnable = [
        (index, quest)
        for index, quest in enumerate(quests, start=1)
        if not quest.claimed and not quest.expired
    ]
    while True:
        answer = input("\nrun which quests? (numbers like '1 3', 'all', or Enter to quit): ").strip().lower()
        if not answer or answer in ("q", "quit", "exit"):
            return []
        if answer == "all":
            return [quest for _, quest in runnable]
        picks = []
        valid = True
        for token in answer.replace(",", " ").split():
            if not token.isdigit() or not (1 <= int(token) <= len(quests)):
                print(f"  [!] '{token}' is not a valid quest number")
                valid = False
                break
            picks.append(quests[int(token) - 1])
        if valid and picks:
            return picks


def run(
    api: DiscordAPI,
    *,
    list_only: bool,
    run_all: bool,
    claim_mode: str,
    games_dir: Path,
    dump_path: Path | None,
    ci: bool = False,
    game_mode: str = "auto",
    experimental_activity: bool = False,
    notify_url: str | None = None,
    human: bool = False,
    skip_chance: float = 0.2,
    max_quests: int = 3,
    only_video: bool = False,
) -> None:
    print("[*] fetching quests...")
    try:
        quests = fetch_quests(api)
    except ApiError as err:
        if err.status == 401:
            raise SystemExit("[!] 401 Unauthorized - the token is wrong or expired")
        raise SystemExit(f"[!] could not fetch quests: {err.message}")

    if dump_path:
        payload = api.get_quests()
        dump_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[i] raw quest JSON saved to {dump_path}")

    try:
        guard_account_state(api=api)
    except SystemExit:
        raise
    except ApiError:
        pass

    print(f"[i] {len(quests)} quest(s) on this account:\n")
    print_quests(quests)

    if list_only:
        return
    if not quests:
        if ci and notify_url:
            webhook_post(notify_url, "AppleQuest run: no quests on this account.")
        return

    if human and ci and skip_chance > 0 and random.random() < skip_chance:
        print("[i] human mode: taking a day off - nothing will be done today")
        if notify_url:
            webhook_post(notify_url, "AppleQuest: taking a day off today.")
        return

    if ci or run_all:
        selected = [q for q in quests if not q.claimed and not q.expired]
    else:
        selected = select_quests(quests)

    if only_video:
        before = len(selected)
        selected = [q for q in selected if (t := q.best_task()) and t.group == "VIDEO" and t.supported]
        print(f"[i] video-only mode: keeping {len(selected)} of {before} quest(s)")

    if human and max_quests and len(selected) > 1:
        runnable = [q for q in selected if (t := q.best_task()) and t.supported_group]
        if runnable:
            count = min(len(runnable), random.randint(1, max_quests))
            selected = random.sample(runnable, count)
            print(f"[i] human mode: doing {count} of {len(runnable)} runnable quest(s) today")

    if not selected:
        print("[i] nothing selected, bye")
        return

    results: dict[str, bool] = {}
    for quest in selected:
        results[quest.name] = run_quest(
            api,
            quest,
            claim_mode,
            games_dir,
            game_mode=game_mode,
            experimental_activity=experimental_activity,
            notify_url=notify_url,
        )
        if ci and quest is not selected[-1]:
            gap = random.uniform(600.0, 2700.0) if human else random.uniform(30.0, 90.0)
            print(f"    [i] waiting {gap / 60:.0f} min before the next quest")
            time.sleep(gap)

    done = sum(1 for ok in results.values() if ok)
    print(f"\n[*] finished: {done}/{len(results)} completed")
    for name, ok in results.items():
        print(f"    {'[+]' if ok else '[-]'} {name}")
    if ci and notify_url:
        lines = [f"AppleQuest run finished: {done}/{len(results)} completed."]
        lines += [f"{'+ ' if ok else '- '}{name}" for name, ok in results.items()]
        webhook_post(notify_url, "\n".join(lines))
