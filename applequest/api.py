"""Discord REST client for the quest endpoints.

Pacing mirrors what a real client looks like: a randomized gap between
requests, Retry-After respected, exponential backoff with jitter on 5xx,
and a full stop on global rate limits. Everything runs on the stdlib.

Every request carries the headers of a real desktop client (User-Agent,
x-super-properties, ...); the Android identity is used only where a quest
specifically requires a mobile client (WATCH_VIDEO_ON_MOBILE enrollment).
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .identity import Identity

API_BASE = "https://discord.com/api/v10"

RETRYABLE = {408, 429, 500, 502, 503, 504}
MAX_RETRIES = 3


class ApiError(Exception):
    def __init__(self, status: int, body: Any, message: str):
        super().__init__(message)
        self.status = status
        self.body = body
        self.message = message

    @property
    def skippable(self) -> bool:
        return self.status in (403, 404, 410)

    @property
    def captcha(self) -> bool:
        return isinstance(self.body, dict) and bool(
            self.body.get("captcha_key") or self.body.get("captcha_sitekey")
        )


class DiscordAPI:
    def __init__(self, token: str, base_url: str = API_BASE, identity: Identity | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.identity = identity or Identity()
        self._last_request = 0.0

    # -- low level ---------------------------------------------------------

    def _pacing_gap(self) -> float:
        return random.uniform(1.2, 1.8)

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        query: dict | None = None,
        identity: str = "desktop",
    ) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        data = json.dumps(body).encode() if body is not None else None
        attempts = 0
        while True:
            gap = self._pacing_gap() - (time.monotonic() - self._last_request)
            if gap > 0:
                time.sleep(gap)
            self._last_request = time.monotonic()

            headers = self.identity.headers_for(identity)
            headers["Authorization"] = self.token
            headers["Accept"] = "*/*"
            if data is not None:
                headers["Content-Type"] = "application/json"

            req = urllib.request.Request(url, data=data, method=method)
            for key, value in headers.items():
                req.add_header(key, value)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                    return json.loads(raw) if raw.strip() else None
            except urllib.error.HTTPError as err:
                raw = err.read().decode("utf-8", "replace")
                try:
                    err_body = json.loads(raw) if raw.strip() else {}
                except json.JSONDecodeError:
                    err_body = raw
                status = err.code

                if status in RETRYABLE and attempts < MAX_RETRIES:
                    attempts += 1
                    if isinstance(err_body, dict):
                        retry_after = err_body.get("retry_after")
                    else:
                        retry_after = None
                    if isinstance(retry_after, (int, float)):
                        delay = float(retry_after)
                    else:
                        delay = float(2 ** attempts)
                    delay += random.uniform(0.2, 0.8)
                    print(f"    [!] HTTP {status}, backing off {delay:.1f}s (attempt {attempts}/{MAX_RETRIES})")
                    time.sleep(delay)
                    continue
                code = err_body.get("code") if isinstance(err_body, dict) else None
                message = err_body.get("message") if isinstance(err_body, dict) else str(err_body)[:200]
                raise ApiError(status, err_body, f"HTTP {status} code={code}: {message}") from err
            except urllib.error.URLError as err:
                if attempts < MAX_RETRIES:
                    attempts += 1
                    delay = float(2 ** attempts) + random.uniform(0.2, 0.8)
                    print(f"    [!] network error ({err.reason}), retrying in {delay:.1f}s")
                    time.sleep(delay)
                    continue
                raise ApiError(0, None, f"network error: {err.reason}") from err

    def get(self, path: str, query: dict | None = None) -> Any:
        return self.request("GET", path, query=query)

    def post(self, path: str, body: dict | None = None, identity: str = "desktop") -> Any:
        return self.request("POST", path, body=body, identity=identity)

    # -- quest endpoints ----------------------------------------------------

    def get_quests(self) -> Any:
        """The client fetches /quests/@me; older builds used /users/@me/quests."""
        try:
            payload = self.get("/quests/@me")
        except ApiError as err:
            if err.status == 404:
                payload = self.get("/users/@me/quests")
            else:
                raise
        return payload

    def enroll(self, quest_id: str, sealed: str | None, raw_blob: str | None, mobile: bool = False) -> Any:
        body = {
            "location": 12 if mobile else 11,
            "is_targeted": False,
            "metadata_sealed": None,
            "traffic_metadata_raw": raw_blob,
            "traffic_metadata_sealed": sealed,
        }
        return self.post(f"/quests/{quest_id}/enroll", body, identity="android" if mobile else "desktop")

    def heartbeat(self, quest_id: str, application_id: str, terminal: bool) -> Any:
        """The response body is the quest's updated user_status."""
        return self.post(
            f"/quests/{quest_id}/heartbeat",
            {"application_id": application_id, "terminal": terminal},
        )

    def heartbeat_stream(self, quest_id: str, stream_key: str, terminal: bool) -> Any:
        return self.post(
            f"/quests/{quest_id}/heartbeat",
            {"stream_key": stream_key, "terminal": terminal},
        )

    def video_progress(self, quest_id: str, timestamp: float) -> Any:
        return self.post(f"/quests/{quest_id}/video-progress", {"timestamp": timestamp})

    def claim_reward(self, quest_id: str, sealed: str | None, raw_blob: str | None) -> Any:
        body = {
            "platform": 0,
            "location": 11,
            "is_targeted": False,
            "metadata_raw": None,
            "metadata_sealed": None,
            "traffic_metadata_raw": raw_blob,
            "traffic_metadata_sealed": sealed,
        }
        return self.post(f"/quests/{quest_id}/claim-reward", body)

    def application_public(self, app_id: str) -> dict | None:
        payload = self.get("/applications/public", query={"application_ids": app_id})
        if isinstance(payload, list) and payload:
            return payload[0]
        return None
