"""AppleQuest - complete Discord quests on your own account.

Local:
    python main.py                 interactive: list quests, pick, complete, claim
    python main.py --list          just list quests and exit
    python main.py --all           run every eligible quest without prompting
    python main.py --game-mode rest   force REST heartbeats for game quests

CI (GitHub Actions):
    python main.py --ci            headless: run all eligible quests, notify
                                    WEBHOOK_URL, never prompt, never claim
                                    (unless AUTO_CLAIM=1)

Token lookup order: --token argument, DISCORD_TOKEN env, TOKEN env (the
name GitHub Actions secrets use), then an interactive prompt (hidden).
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from applequest import __version__
from applequest.api import ApiError, DiscordAPI
from applequest.identity import Identity
from applequest.runner import CLAIM_ASK, CLAIM_AUTO, CLAIM_NEVER, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="applequest",
        description="Complete Discord quests on your own account (ToS-violating selfbot; use at your own risk).",
    )
    parser.add_argument("--version", action="version", version=f"applequest {__version__}")
    parser.add_argument("--token", help="Discord account token (prefer DISCORD_TOKEN / TOKEN env vars)")
    parser.add_argument("--list", action="store_true", help="list quests and exit")
    parser.add_argument("--all", action="store_true", help="run every eligible quest without prompting")
    parser.add_argument("--ci", action="store_true", help="headless mode for GitHub Actions (auto-detected)")
    parser.add_argument("--game-mode", choices=("auto", "client", "rest"), default="auto",
                        help="how PLAY_ON_DESKTOP quests are driven: dummy exe via the running "
                             "Discord desktop client, forged REST heartbeats, or auto-pick (default)")
    parser.add_argument("--experimental-activity", action="store_true",
                        help="try PLAY_ACTIVITY quests via a stream-key heartbeat (often rejected)")
    parser.add_argument("--only-video", action="store_true",
                        help="only complete video quests (WATCH_VIDEO / mobile) - the safest type")
    parser.add_argument("--human", action="store_true",
                        help="pace like a human: a random 1-3 quest subset, 10-45 min gaps between "
                             "quests, and in CI a chance to skip the day entirely")
    parser.add_argument("--skip-chance", type=float, default=0.2, metavar="P",
                        help="day-skip probability in human mode, CI only (default 0.2)")
    parser.add_argument("--max-quests", type=int, default=3, metavar="N",
                        help="max quests per run in human mode (default 3)")
    parser.add_argument("--auto-claim", action="store_true", help="claim rewards without asking")
    parser.add_argument("--no-claim", action="store_true", help="never claim rewards")
    parser.add_argument("--dump", metavar="PATH", help="save the raw quest JSON to PATH")
    parser.add_argument("--games-dir", default="games", help="folder for dummy game executables (default: ./games)")
    return parser


def resolve_token(cli_token: str | None) -> str:
    token = cli_token or os.environ.get("DISCORD_TOKEN") or os.environ.get("TOKEN") or ""
    token = token.strip().strip('"')
    if token:
        return token
    print("AppleQuest needs your Discord account token.")
    print("How to get it: open discord.com in your browser, F12 > Network, reload,")
    print("click any request to discord.com/api and copy the 'authorization' header.")
    print("The token stays in memory only - AppleQuest never writes it to disk.")
    token = getpass.getpass("token: ").strip().strip('"')
    if not token:
        raise SystemExit("[!] no token given")
    return token


def main() -> int:
    args = build_parser().parse_args()
    if args.no_claim and args.auto_claim:
        print("[!] --no-claim and --auto-claim contradict each other")
        return 2
    if not 0.0 <= args.skip_chance <= 1.0:
        print("[!] --skip-chance must be between 0 and 1")
        return 2
    if args.max_quests < 1:
        print("[!] --max-quests must be at least 1")
        return 2

    ci = args.ci or os.environ.get("GITHUB_ACTIONS") == "true"
    notify_url = os.environ.get("WEBHOOK_URL") or None

    if args.auto_claim:
        claim_mode = CLAIM_AUTO
    elif args.no_claim or ci:
        claim_mode = CLAIM_AUTO if (ci and os.environ.get("AUTO_CLAIM") == "1") else CLAIM_NEVER
    else:
        claim_mode = CLAIM_ASK

    print("AppleQuest - Discord quest selfbot")
    print("[!] This automates your account, which violates Discord's Terms of")
    print("    Service. Discord has enforced against quest automation since")
    print("    April 2026 and can act on the whole account. You run this anyway.\n")

    token = resolve_token(args.token)
    identity = Identity()
    identity.refresh_build_number()
    api = DiscordAPI(token, identity=identity)

    dump_path = Path(args.dump) if args.dump else None
    if dump_path and dump_path.parent != Path("."):
        dump_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        run(
            api,
            list_only=args.list,
            run_all=args.all,
            claim_mode=claim_mode,
            games_dir=Path(args.games_dir),
            dump_path=dump_path,
            ci=ci,
            game_mode=args.game_mode,
            experimental_activity=args.experimental_activity,
            notify_url=notify_url,
            human=args.human,
            skip_chance=args.skip_chance,
            max_quests=args.max_quests,
            only_video=args.only_video,
        )
    except (KeyboardInterrupt, EOFError):
        print("\n[*] stopped")
    except ApiError as err:
        print(f"[!] API error: {err.message}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
