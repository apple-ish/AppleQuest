# AppleQuest

Complete Discord quests automatically — **no game downloads, no PC required**.
Run it from GitHub (works from your phone) or locally on Windows.

---

> [!WARNING]
> This is a selfbot: it automates your Discord **user account**, which violates
> the [Discord Terms of Service](https://discord.com/terms). Discord has been
> enforcing against quest automation since **April 2026** and can warn or
> suspend accounts that use it. Use an account you can afford to lose.
> Running it on GitHub Actions also technically violates GitHub's
> [Acceptable Use Policy](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies).

---

## Quick start (GitHub — works from Android)

**1. Fork this repo** (button top-right).

**2. Add your token:** your fork → **Settings** → **Secrets and variables** →
**Actions** → **New repository secret**:

| Secret | Required | What it does |
|---|---|---|
| `TOKEN` | yes | your Discord account token |
| `MODE` | no | set to `1` to **only do video quests** (safest mode) |
| `WEBHOOK_URL` | no | get a Discord DM/notification when quests finish |
| `AUTO_CLAIM` | no | set to `1` to auto-claim rewards (can hit a captcha) |

> [!NOTE]
> GitHub **never copies secrets when a repo is forked** — you must add them
> yourself in your fork. If you forget the `TOKEN`, the workflow will stop and
> print these same instructions instead of failing with an error.

**3. Enable Actions:** your fork → **Actions** tab → click **Enable workflows**.

Done. It runs once a day automatically, or trigger it anytime:
**Actions** → **Quests** → **Run workflow**.

- Claim your rewards manually in the Discord app (Quests page) — safer that way.
- If scheduled runs stop after ~60 days of no commits: push any tiny commit.

### Getting your token

Open `https://discord.com` in a desktop browser → log in → `F12` → **Network**
tab → reload the page → click any request to `discord.com/api` → **Request
Headers** → copy the `authorization` value. Never paste your token into random
"token grabber" websites.

### Which mode should I use?

| Mode | Completes | Risk |
|---|---|---|
| default | all quest types (videos, games, consoles) | game quests use forged heartbeats from GitHub's cloud IPs — the most detectable thing |
| `MODE=1` | video quests only | much safer — indistinguishable pacing from the real player |

For the safest possible setup: keep `MODE=1` on GitHub, and run game quests
locally in client mode (below).

## Local usage (Windows, Python 3.10+, zero dependencies)

```powershell
$env:DISCORD_TOKEN = "your token"

python main.py                    # interactive: list, pick, complete
python main.py --only-video       # safest: video quests only
python main.py --all --auto-claim # run everything, claim everything
python main.py --human            # 1-3 random quests, 10-45 min apart
python main.py --list             # just look, do nothing
```

### Game quests: two ways

- **Client mode** (default when the Discord desktop app is running): AppleQuest
  copies a tiny Windows system file under the game's real `.exe` name and runs
  it hidden. Your own Discord client sees the "game" and reports the play time
  itself — no download, and it looks real to Discord. **Safest option.**
- **REST mode** (automatic on GitHub): AppleQuest sends the "playing game X"
  heartbeats itself. Works anywhere but is the most detectable technique.

So: **Discord open → game quests are safe; Discord closed or GitHub → consider
`--only-video` / `MODE=1`.**

## What it can and can't do

| Quest type | Status |
|---|---|
| Watch a video (desktop + mobile) | done — real player pacing |
| Play a game on desktop / Xbox / PlayStation | done — client mode locally, heartbeats on CI |
| Play an activity | experimental (`--experimental-activity`), often rejected |
| Stream a game | impossible to fake — skipped |
| Earn an achievement | impossible / riskiest — skipped |

## Troubleshooting

| Problem | Fix |
|---|---|
| `401 Unauthorized` | token wrong or expired — grab a fresh one |
| Workflow does nothing | check the Actions log; missing `TOKEN` prints setup steps |
| Schedule stopped | GitHub disables it after 60 idle days — push a commit |
| Game quest no progress (local) | Discord desktop must be open + quest visible in your Quests page |
| Claim hits a captcha | claim manually in the Discord app |
| Everything broke overnight | Discord changed its private API (happens) — run `python main.py --dump quests.json` and compare |

## Credits

Built on endpoint research from
[Orion](https://github.com/nyxxbit/discord-quest-completer) and the
[GitHub-Actions selfbot architecture](https://github.com/aiko-chan-ai/Discord-Quest-Auto-Completion-Selfbot)
by aiko-chan-ai, descending from [aamiaa's gist](https://gist.github.com/aamiaa/204cd9d42013ded9faf646fae7f89fbb).
Quest icons and names belong to Discord; this project is not affiliated with them.
