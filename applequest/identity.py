"""Client identity spoofing: the headers a real Discord client sends.

Two identities:
- desktop: the Windows Electron client (User-Agent, x-super-properties,
  origin/referer and browser security headers)
- android: the Discord Android app, used for WATCH_VIDEO_ON_MOBILE quests
  whose enrollment only counts from a mobile client

The client build number is scraped from discord.com's shipped JS at startup
(best-effort; falls back to a known-good number) so x-super-properties look
current rather than frozen at whatever this file shipped with.
"""

from __future__ import annotations

import base64
import json
import random
import re
import urllib.request
import uuid

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) discord/1.0.9236 Chrome/138.0.7204.251 "
    "Electron/37.6.0 Safari/537.36"
)
ANDROID_USER_AGENT = "Discord-Android/316011;RNA"

FALLBACK_BUILD_NUMBER = 539951
FALLBACK_NATIVE_BUILD_NUMBER = 81687

_ASSET_RE = re.compile(r"assets/web\.([0-9a-f]+)\.js")
_BUILD_RE = re.compile(r'buildNumber["\s:]+["\s]*(\d{5,7})')


def _super_properties(properties: dict) -> str:
    return base64.b64encode(json.dumps(properties).encode()).decode()


class Identity:
    def __init__(self):
        self.launch_id = str(uuid.uuid4())
        self.launch_signature = str(uuid.uuid4())
        self.heartbeat_session_id = str(uuid.uuid4())
        self.android_vendor_id = str(uuid.uuid4())
        self._build_number: int | None = None

    # -- build number -------------------------------------------------------

    @property
    def build_number(self) -> int:
        return self._build_number or FALLBACK_BUILD_NUMBER

    def refresh_build_number(self) -> None:
        try:
            self._build_number = self._scrape_build_number()
        except Exception:
            self._build_number = None

    def _scrape_build_number(self) -> int | None:
        req = urllib.request.Request(
            "https://discord.com/app",
            headers={"User-Agent": DESKTOP_USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", "replace")
        match = _ASSET_RE.search(html)
        if not match:
            return None
        req = urllib.request.Request(
            f"https://discord.com/assets/web.{match.group(1)}.js",
            headers={"User-Agent": DESKTOP_USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            script = resp.read(2_000_000).decode("utf-8", "replace")
        build = _BUILD_RE.search(script)
        return int(build.group(1)) if build else None

    # -- identities ---------------------------------------------------------

    def desktop_properties(self) -> dict:
        return {
            "os": "Windows",
            "browser": "Discord Client",
            "release_channel": "stable",
            "client_version": "1.0.9236",
            "os_version": "10.0.19045",
            "os_arch": "x64",
            "app_arch": "x64",
            "system_locale": "en-US",
            "has_client_mods": False,
            "client_launch_id": self.launch_id,
            "browser_user_agent": DESKTOP_USER_AGENT,
            "browser_version": "37.6.0",
            "os_sdk_version": "19045",
            "client_build_number": self.build_number,
            "native_build_number": FALLBACK_NATIVE_BUILD_NUMBER,
            "client_event_source": None,
            "launch_signature": self.launch_signature,
            "client_heartbeat_session_id": self.heartbeat_session_id,
            "client_app_state": "focused",
        }

    def android_properties(self) -> dict:
        return {
            "os": "Android",
            "browser": "Discord Android",
            "device": "b0q",
            "client_version": "316.11 - rn",
            "release_channel": "googleRelease",
            "device_vendor_id": self.android_vendor_id,
            "design_id": 2,
            "os_version": "28",
            "client_build_number": 316011,
            "launch_signature": str(random.randrange(10 ** 18, 10 ** 19)),
            "client_app_state": "active",
        }

    def headers_for(self, identity: str = "desktop") -> dict:
        if identity == "android":
            return {
                "User-Agent": ANDROID_USER_AGENT,
                "x-super-properties": _super_properties(self.android_properties()),
            }
        return {
            "User-Agent": DESKTOP_USER_AGENT,
            "accept-language": "en-US",
            "x-debug-options": "bugReporterEnabled",
            "x-discord-locale": "en-US",
            "x-super-properties": _super_properties(self.desktop_properties()),
            "origin": "https://discord.com",
            "referer": "https://discord.com/channels/@me",
            "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
