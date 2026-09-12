"""End-to-end smoke test for AppleQuest against a mock Discord API.

Covers: model parsing, /quests/@me 404 fallback, the local interactive flow
(dummy-exe client mode for game quests, real process launch), the CI flow
(REST heartbeats, headless, webhook notifications), Android-identity
enrollment for mobile-only video quests, and console-task heartbeats.
"""

import base64
import contextlib
import io
import json
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
TMP = Path(tempfile.mkdtemp(prefix="aq_smoke_"))
GAMES_DIR = TMP / "games"

from applequest import models, stub, video as video_mod, game as game_mod, runner as runner_mod  # noqa: E402
from applequest.api import DiscordAPI  # noqa: E402
from applequest.identity import ANDROID_USER_AGENT, DESKTOP_USER_AGENT, Identity  # noqa: E402
from applequest.runner import CLAIM_AUTO, CLAIM_NEVER  # noqa: E402

STATE = {
    "video_progress": 0.0,
    "video_progress_q5": 0.0,
    "video_posts": [],
    "enrolls": [],
    "claims": [],
    "beats": {},
    "heartbeats": [],
    "game_polls": 0,
    "app_calls": [],
    "webhook_posts": [],
    "fallback_mode": False,
}

VIDEO_KEYS = {"q1": ("WATCH_VIDEO", 15.0), "q5": ("WATCH_VIDEO_ON_MOBILE", 12.0)}


def quests_payload():
    future = time.time() + 2 * 24 * 3600
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(future))
    q2_value = min(900, STATE["game_polls"] * 60)
    return [
        {
            "id": "q1",
            "traffic_metadata_raw": "rawblob-q1",
            "traffic_metadata_sealed": "sealedblob-q1",
            "config": {
                "expires_at": iso,
                "messages": {"quest_name": "Watch a Trailer"},
                "rewards_config": {"rewards": [{"type": "ORBS", "messages": {"name": "15 Orbs"}}]},
                "taskConfigV2": {"tasks": {"WATCH_VIDEO": {"target": 15, "applications": [{"id": "123"}]}}},
            },
            "user_status": {"progress": {"WATCH_VIDEO": {"value": STATE["video_progress"]}}},
        },
        {
            "id": "q2",
            "traffic_metadata_raw": "rawblob-q2",
            "config": {
                "messages": {"quest_name": "Play Fake Game"},
                "rewards_config": {"rewards": [{"messages": {"name": "Avatar Hat"}}]},
                "taskConfigV2": {
                    "tasks": {
                        "PLAY_ON_DESKTOP": {"target": 10, "applications": [{"id": "999"}]},
                        "STREAM_ON_DESKTOP": {"target": 900, "applications": [{"id": "999"}]},
                    }
                },
            },
            "user_status": {"progress": {"PLAY_ON_DESKTOP": {"value": q2_value}}},
        },
        {
            "id": "q3",
            "config": {
                "messages": {"quest_name": "Stream Something"},
                "rewards_config": {"rewards": [{"messages": {"name": "Decoration"}}]},
                "taskConfigV2": {"tasks": {"STREAM_ON_DESKTOP": {"target": 900, "applications": [{"id": "999"}]}}},
            },
            "user_status": {},
        },
        {
            "id": "q4",
            "config": {
                "messages": {"quest_name": "Get an Achievement"},
                "rewards_config": {"rewards": [{"messages": {"name": "Badge"}}]},
                "taskConfigV2": {"tasks": {"ACHIEVEMENT_IN_ACTIVITY": {"target": 1, "applications": [{"id": "555"}]}}},
            },
            "user_status": {},
        },
        {
            "id": "q5",
            "traffic_metadata_raw": "rawblob-q5",
            "config": {
                "messages": {"quest_name": "Mobile Orbs Intro"},
                "rewards_config": {"rewards": [{"messages": {"name": "5 Orbs"}}]},
                "taskConfigV2": {"tasks": {"WATCH_VIDEO_ON_MOBILE": {"target": 12, "applications": [{"id": "321"}]}}},
            },
            "user_status": {"progress": {"WATCH_VIDEO_ON_MOBILE": {"value": STATE["video_progress_q5"]}}},
        },
        {
            "id": "q6",
            "config": {
                "messages": {"quest_name": "Play On Xbox"},
                "rewards_config": {"rewards": [{"messages": {"name": "Xbox Reward"}}]},
                "taskConfigV2": {"tasks": {"PLAY_ON_XBOX": {"target": 20, "applications": [{"id": "777"}]}}},
            },
            "user_status": {},
        },
    ]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/v10/quests/@me" and not STATE["fallback_mode"]:
            STATE["game_polls"] += 1
            return self._send(quests_payload())
        if parsed.path == "/api/v10/users/@me/quests":
            STATE["game_polls"] += 1
            return self._send(quests_payload())
        if parsed.path == "/api/v10/applications/public":
            query = urllib.parse.parse_qs(parsed.query)
            STATE["app_calls"].extend(query.get("application_ids", []))
            return self._send([{"id": "999", "name": "Fake Game", "executables": [{"os": "win32", "name": "FakeGame.exe"}]}])
        return self._send({"message": "Not Found", "code": 0}, status=404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path.split("/")
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        ua = self.headers.get("User-Agent") or ""
        if parsed.path.startswith("/api/webhooks/"):
            STATE["webhook_posts"].append(body.get("content", ""))
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path.endswith("/enroll"):
            STATE["enrolls"].append((parts[4], body, ua))
            return self._send({})
        if parsed.path.endswith("/video-progress"):
            quest_id = parts[4]
            key, target = VIDEO_KEYS[quest_id]
            ts = float(body["timestamp"])
            STATE["video_posts"].append((quest_id, ts))
            state_key = "video_progress_q5" if quest_id == "q5" else "video_progress"
            STATE[state_key] = max(STATE[state_key], ts)
            payload = {"progress": {key: {"value": STATE[state_key]}}}
            if STATE[state_key] >= target:
                payload["completed_at"] = "now"
            return self._send(payload)
        if parsed.path.endswith("/heartbeat"):
            quest_id = parts[4]
            STATE["beats"][quest_id] = STATE["beats"].get(quest_id, 0) + 1
            STATE["heartbeats"].append((quest_id, body))
            value = STATE["beats"][quest_id] * 60
            task_key = "PLAY_ON_XBOX" if quest_id == "q6" else "PLAY_ON_DESKTOP"
            payload = {"progress": {task_key: {"value": value}}}
            if value >= 10:
                payload["completed_at"] = "now"
            return self._send(payload)
        if parsed.path.endswith("/claim-reward"):
            STATE["claims"].append(parts[4])
            return self._send({"claimed_at": 12345})
        return self._send({"message": "Not Found", "code": 0}, status=404)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()

failures = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" ({detail})" if detail and not condition else ""))
    if not condition:
        failures.append(label)


# ---- unit: identity ---------------------------------------------------------
print("== identity")
identity = Identity()
desktop_headers = identity.headers_for("desktop")
android_headers = identity.headers_for("android")
check("desktop UA is the client UA", desktop_headers["User-Agent"] == DESKTOP_USER_AGENT)
check("android UA is the android app UA", android_headers["User-Agent"] == ANDROID_USER_AGENT)
props = json.loads(base64.b64decode(desktop_headers["x-super-properties"]))
check("x-super-properties decodes to client properties", props["browser"] == "Discord Client" and props["os"] == "Windows")
android_props = json.loads(base64.b64decode(android_headers["x-super-properties"]))
check("android super-properties", android_props["os"] == "Android" and android_props["browser"] == "Discord Android")

# ---- unit: models -----------------------------------------------------------
print("== models")
check("classify PLAY_ON_DESKTOP -> GAME", models.classify_task("PLAY_ON_DESKTOP") == "GAME")
check("classify PLAY_ON_DESKTOP_V2 -> GAME", models.classify_task("PLAY_ON_DESKTOP_V2") == "GAME")
check("classify WATCH_VIDEO_ON_MOBILE -> VIDEO", models.classify_task("WATCH_VIDEO_ON_MOBILE") == "VIDEO")
check("classify STREAM_ON_DESKTOP -> STREAM", models.classify_task("STREAM_ON_DESKTOP") == "STREAM")
check("classify PLAY_ACTIVITY -> ACTIVITY", models.classify_task("PLAY_ACTIVITY") == "ACTIVITY")

mixed = {
    "id": "m1",
    "config": {
        "messages": {"quest_name": "Mixed"},
        "rewards_config": {"rewards": [{"messages": {"name": "R"}}]},
        "taskConfigV2": {
            "tasks": {
                "STREAM_ON_DESKTOP": {"target": 900, "applications": [{"id": "9"}]},
                "PLAY_ON_DESKTOP": {"target": 900, "applications": [{"id": "9"}]},
                "WATCH_VIDEO": {"target": 60, "applications": [{"id": "9"}]},
            }
        },
    },
    "user_status": {},
}
q = models.parse_quest(mixed)
check("mixed quest prefers VIDEO", q.best_task().group == "VIDEO")

legacy = {
    "id": "m2",
    "config": {
        "messages": {"questName": "LegacyCamel"},
        "rewardsConfig": {"rewards": [{"messages": {"name": "RR"}}]},
        "application": {"id": "42"},
        "taskConfig": {"tasks": {"PLAY_ON_DESKTOP": {"target": 600}}},
    },
    "userStatus": {"enrolledAt": 1, "completedAt": None, "progress": {"PLAY_ON_DESKTOP": {"value": 120}}},
}
q = models.parse_quest(legacy)
check("camelCase payload parses", q.name == "LegacyCamel" and q.enrolled and not q.completed)
check("legacy app id + progress read", q.best_task().app_id == "42" and q.progress_for("PLAY_ON_DESKTOP") == 120)

console = models.parse_quest({
    "id": "m3",
    "config": {"messages": {"quest_name": "X"}, "taskConfigV2": {"tasks": {"PLAY_ON_XBOX": {"target": 60}}}},
    "user_status": {},
})
check("console task supported via heartbeat", console.best_task().supported is True and console.best_task().group == "GAME")

blocked, suspended = models.find_account_blocks({"quests": [], "quest_enrollment_blocked_until": "2026-10-01"})
check("enrollment block detected", blocked == "2026-10-01" and suspended is None)

# ---- api: 404 fallback --------------------------------------------------------
print("== api fallback")
api = DiscordAPI("fake-token", base_url=f"http://127.0.0.1:{port}/api/v10", identity=identity)
data = api.get_quests()
check("list payload accepted", isinstance(data, list) and len(data) == 6)
STATE["fallback_mode"] = True
data = api.get_quests()
check("404 falls back to /users/@me/quests", isinstance(data, list) and len(data) == 6)
STATE["fallback_mode"] = False


class FakeTime:
    """Replaces a module's `time` reference: sleep is instant, clocks real.

    Assigning mod.time = FakeTime() only affects that module, never the
    global stdlib time module (which api.py's pacing must keep).
    """

    sleep = staticmethod(lambda s: None)
    monotonic = staticmethod(time.monotonic)
    time = staticmethod(time.time)


video_mod.time = FakeTime()
game_mod.time = FakeTime()
runner_mod.time = FakeTime()

# ---- local flow: client-mode game + android enroll + console heartbeat -------
print("== local flow (client-mode game, android enroll, console heartbeat)")
game_mod.stub.discord_running = lambda: True

stdout = io.StringIO()
with contextlib.redirect_stdout(stdout):
    runner_mod.run(
        api,
        list_only=False,
        run_all=True,
        claim_mode=CLAIM_AUTO,
        games_dir=GAMES_DIR,
        dump_path=None,
        game_mode="client",
    )
out = stdout.getvalue()

check("video quest enrolled from desktop identity",
      any(qid == "q1" and b["location"] == 11 and "Discord-Android" not in ua for qid, b, ua in STATE["enrolls"]),
      f"enrolls={STATE['enrolls']}")
check("mobile video quest enrolled from android identity",
      any(qid == "q5" and b["location"] == 12 and ua == ANDROID_USER_AGENT for qid, b, ua in STATE["enrolls"]),
      f"enrolls={[(q, b.get('location'), ua[:20]) for q, b, ua in STATE['enrolls']]}")
check("sealed/raw blobs passed through on enroll",
      any(qid == "q1" and b["traffic_metadata_raw"] == "rawblob-q1" and b["traffic_metadata_sealed"] == "sealedblob-q1"
          for qid, b, _ in STATE["enrolls"]))
check("desktop video posted to target", any(qid == "q1" and ts >= 15 for qid, ts in STATE["video_posts"]))
check("mobile video posted to target", any(qid == "q5" and ts >= 12 for qid, ts in STATE["video_posts"]))
def _per_quest_monotonic(posts):
    by_quest: dict[str, list[float]] = {}
    for quest_id, ts in posts:
        by_quest.setdefault(quest_id, []).append(ts)
    return all(ts_list == sorted(ts_list) for ts_list in by_quest.values())


check("video timestamps monotonic per quest", _per_quest_monotonic(STATE["video_posts"]),
      f"posts={STATE['video_posts']}")
check("client-mode game fetched app metadata", "999" in STATE["app_calls"], f"app_calls={STATE['app_calls']}")
check("console quest completed via heartbeat", STATE["beats"].get("q6", 0) >= 1)
check("client-mode game used no heartbeats", STATE["beats"].get("q2", 0) == 0, f"beats={STATE['beats']}")
check("all four rewards claimed", sorted(STATE["claims"]) == ["q1", "q2", "q5", "q6"], f"claims={STATE['claims']}")
check("summary says 4/6 completed", "4/6 completed" in out)
check("stream skip explained", "Go Live" in out)
check("achievement skip explained", "achievement quest" in out)
check("no leftovers in games dir", not any(GAMES_DIR.glob("*/FakeGame.exe")))
check("no webhook posts locally", STATE["webhook_posts"] == [])

# ---- CI flow: rest-mode heartbeats, headless, webhook -------------------------
print("== CI flow (rest-mode heartbeats, headless, webhook)")
STATE["video_progress"] = 0.0
STATE["video_progress_q5"] = 0.0
STATE["video_posts"] = []
STATE["enrolls"] = []
STATE["claims"] = []
STATE["beats"] = {}
STATE["heartbeats"] = []
STATE["app_calls"] = []
game_mod.stub.discord_running = lambda: False

webhook_url = f"http://127.0.0.1:{port}/api/webhooks/WHID/WHTOKEN"
stdout = io.StringIO()
with contextlib.redirect_stdout(stdout):
    runner_mod.run(
        api,
        list_only=False,
        run_all=True,
        claim_mode=CLAIM_NEVER,
        games_dir=GAMES_DIR,
        dump_path=None,
        ci=True,
        game_mode="rest",
        notify_url=webhook_url,
    )
ci_out = stdout.getvalue()

check("CI game quest used heartbeats", STATE["beats"].get("q2", 0) >= 1, f"beats={STATE['beats']}")
check("CI heartbeat body shape (application_id + terminal)",
      any(qid == "q2" and b.get("application_id") == "999" and b.get("terminal") is False
          for qid, b in STATE["heartbeats"]),
      f"heartbeats={STATE['heartbeats']}")
check("terminal heartbeat sent on completion",
      any(qid == "q2" and b.get("terminal") is True for qid, b in STATE["heartbeats"]),
      f"heartbeats={STATE['heartbeats']}")
check("rest mode skipped app metadata", STATE["app_calls"] == [], f"app_calls={STATE['app_calls']}")
check("CI never claimed", STATE["claims"] == [], f"claims={STATE['claims']}")
check("CI unclaimed message shown", "reward left unclaimed" in ci_out)
check("webhook notified per completed quest", sum(1 for c in STATE["webhook_posts"] if "Quest completed" in c) >= 4,
      f"posts={STATE['webhook_posts']}")
check("webhook summary sent", any("AppleQuest run finished: 4/6 completed" in c for c in STATE["webhook_posts"]),
      f"posts={STATE['webhook_posts']}")
check("CI ran headless without prompts", "run which quests" not in ci_out)

# ---- human mode: day-off, quest subset, long gaps -----------------------------
print("== human mode (day-off, subset selection, long gaps)")


class FakeRandom:
    """Deterministic stand-in for runner's `random` module binding."""

    def __init__(self, rand_value, sample_k):
        self.rand_value = rand_value
        self.sample_k = sample_k

    def random(self):
        return self.rand_value

    def randint(self, a, b):
        return self.sample_k

    def sample(self, population, k):
        return list(population)[:k]

    def uniform(self, a, b):
        return float(a)

    def shuffle(self, seq):
        return None


class RecordingTime:
    """Records every sleep duration the runner asks for."""

    def __init__(self):
        self.sleeps = []
        self.monotonic = staticmethod(time.monotonic)
        self.time = staticmethod(time.time)

    def sleep(self, seconds):
        self.sleeps.append(seconds)


real_runner_random = runner_mod.random
real_runner_time = runner_mod.time


def reset_run_state():
    STATE["video_progress"] = 0.0
    STATE["video_progress_q5"] = 0.0
    STATE["video_posts"] = []
    STATE["enrolls"] = []
    STATE["claims"] = []
    STATE["beats"] = {}
    STATE["heartbeats"] = []
    STATE["app_calls"] = []
    STATE["webhook_posts"] = []


# day-off: random() < skip_chance means do nothing
reset_run_state()
runner_mod.random = FakeRandom(rand_value=0.05, sample_k=2)
rec = RecordingTime()
runner_mod.time = rec
stdout = io.StringIO()
with contextlib.redirect_stdout(stdout):
    runner_mod.run(
        api,
        list_only=False,
        run_all=True,
        claim_mode=CLAIM_NEVER,
        games_dir=GAMES_DIR,
        dump_path=None,
        ci=True,
        game_mode="rest",
        notify_url=webhook_url,
        human=True,
        skip_chance=0.2,
        max_quests=3,
    )
day_off_out = stdout.getvalue()
check("human day-off: nothing enrolled", STATE["enrolls"] == [], f"enrolls={STATE['enrolls']}")
check("human day-off: message shown", "day off" in day_off_out)
check("human day-off: webhook notified", any("day off" in c for c in STATE["webhook_posts"]),
      f"posts={STATE['webhook_posts']}")

# normal human day: no skip, pick 2 of the 4 runnable quests, 10-45 min gaps
reset_run_state()
runner_mod.random = FakeRandom(rand_value=0.9, sample_k=2)
rec = RecordingTime()
runner_mod.time = rec
stdout = io.StringIO()
with contextlib.redirect_stdout(stdout):
    runner_mod.run(
        api,
        list_only=False,
        run_all=True,
        claim_mode=CLAIM_NEVER,
        games_dir=GAMES_DIR,
        dump_path=None,
        ci=True,
        game_mode="rest",
        notify_url=webhook_url,
        human=True,
        skip_chance=0.2,
        max_quests=3,
    )
human_out = stdout.getvalue()
enrolled_ids = sorted(qid for qid, _, _ in STATE["enrolls"])
check("human mode enrolled only the sampled subset", len(STATE["enrolls"]) == 2,
      f"enrolls={enrolled_ids}")
check("human mode only picked runnable quests",
      all(qid in ("q1", "q2", "q5", "q6") for qid in enrolled_ids),
      f"enrolls={enrolled_ids}")
check("human mode subset announced", "doing 2 of 4 runnable quest(s)" in human_out)
check("human mode long gap between quests", max(rec.sleeps) >= 600.0,
      f"sleeps={rec.sleeps}")
check("human mode summary counts subset", "2/2 completed" in human_out)

runner_mod.random = real_runner_random
runner_mod.time = real_runner_time

# ---- video-only mode (the MODE=1 secret) --------------------------------------
print("== video-only mode (MODE=1)")
reset_run_state()
stdout = io.StringIO()
with contextlib.redirect_stdout(stdout):
    runner_mod.run(
        api,
        list_only=False,
        run_all=True,
        claim_mode=CLAIM_NEVER,
        games_dir=GAMES_DIR,
        dump_path=None,
        ci=True,
        only_video=True,
    )
video_only_out = stdout.getvalue()
enrolled_ids = sorted(qid for qid, _, _ in STATE["enrolls"])
check("video-only enrolled exactly the video quests", enrolled_ids == ["q1", "q5"],
      f"enrolls={enrolled_ids}")
check("video-only sent no heartbeats", STATE["heartbeats"] == [], f"heartbeats={STATE['heartbeats']}")
check("video-only mode announced", "video-only mode: keeping 2 of 6 quest(s)" in video_only_out,
      "message missing")
check("video-only summary 2/2", "2/2 completed" in video_only_out)

server.shutdown()
print()
if failures:
    print(f"SMOKE TEST FAILED: {len(failures)} check(s): {failures}")
    print("\n----- captured local output -----")
    print(out)
    print("\n----- captured CI output -----")
    print(ci_out)
    sys.exit(1)
print("SMOKE TEST PASSED")
