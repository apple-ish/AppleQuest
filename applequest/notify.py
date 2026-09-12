"""Webhook notifications: how an Android user knows the CI run finished."""

from __future__ import annotations

import json
import urllib.request


def webhook_post(url: str | None, content: str) -> bool:
    if not url:
        return False
    data = json.dumps({"content": str(content)[:2000]}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "AppleQuest"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True
    except Exception as err:
        print(f"    [!] webhook notification failed: {err}")
        return False


def quest_link(quest_id: str, name: str) -> str:
    return f"[{name}](https://discord.com/quests/{quest_id})"
