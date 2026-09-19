<div align="center">

# 🍎 AppleQuest

*completes discord quests automatically — no game downloads, no pc required*

<img src="https://img.shields.io/badge/runs%20on-github%20actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white" alt="actions badge"/>
<img src="https://img.shields.io/badge/works%20on-android-3DDC84?style=for-the-badge&logo=android&logoColor=white" alt="android badge"/>
<img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="python badge"/>

*run it from github (works from your phone) or locally on windows.*

</div>

---

> [!WARNING]
> This is a selfbot: it automates your Discord **user account**, which violates
> the [Discord Terms of Service](https://discord.com/terms). Discord has been
> enforcing against quest automation since **April 2026** and can warn or
> suspend accounts that use it. Use an account you can afford to lose.
> Running it on GitHub Actions also technically violates GitHub's
> [Acceptable Use Policy](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies).

---

## 🍏 quick start (github — works from android)

**1. fork this repo** (button top-right of
[apple-ish/AppleQuest](https://github.com/apple-ish/AppleQuest))

**2. add your token:** your fork → **settings** → **secrets and variables** →
**actions** → **new repository secret**:

| secret | required | what it does |
|---|:---:|---|
| `TOKEN` | ✅ | your discord account token |
| `MODE` | — | set to `1` to **only do video quests** (safest mode) |
| `WEBHOOK_URL` | — | get a discord dm/notification when quests finish |
| `AUTO_CLAIM` | — | set to `1` to auto-claim rewards (can hit a captcha) |

> [!NOTE]
> GitHub **never copies secrets when a repo is forked** — you must add them
> yourself in your fork. If you forget the `TOKEN`, the workflow will stop and
> print these same instructions instead of failing with an error.

**3. enable actions:** your fork → **actions** tab → click **enable workflows**.

done. it runs once a day automatically, or trigger it anytime:
**actions** → **quests** → **run workflow**.

- claim your rewards manually in the discord app (quests page) — safer that way
- if scheduled runs stop after ~60 days of no commits: push any tiny commit

### 🍎 getting your token

open `https://discord.com` in a desktop browser → log in → `f12` → **network**
tab → reload the page → click any request to `discord.com/api` → **request
headers** → copy the `authorization` value. never paste your token into random
"token grabber" websites.

### 🧺 which mode should i use?

| mode | completes | risk |
|---|---|---|
| default | all quest types (videos, games, consoles) | game quests use forged heartbeats from github's cloud ips — the most detectable thing |
| `MODE=1` | video quests only | much safer — indistinguishable pacing from the real player |

for the safest possible setup: keep `MODE=1` on github, and run game quests
locally in client mode (below).

## 🍏 local usage (windows, python 3.10+, zero dependencies)

```powershell
$env:DISCORD_TOKEN = "your token"

python main.py                    # interactive: list, pick, complete
python main.py --only-video       # safest: video quests only
python main.py --all --auto-claim # run everything, claim everything
python main.py --human            # 1-3 random quests, 10-45 min apart
python main.py --list             # just look, do nothing
```

### 🍎 game quests: two ways

- **client mode** (default when the discord desktop app is running): applequest
  copies a tiny windows system file under the game's real `.exe` name and runs
  it hidden. your own discord client sees the "game" and reports the play time
  itself — no download, and it looks real to discord. **safest option.**
- **rest mode** (automatic on github): applequest sends the "playing game x"
  heartbeats itself. works anywhere but is the most detectable technique.

so: **discord open → game quests are safe; discord closed or github → consider
`--only-video` / `MODE=1`.**

## 🧺 what it can and can't do

| quest type | status |
|---|---|
| watch a video (desktop + mobile) | ✅ done — real player pacing |
| play a game on desktop / xbox / playstation | ✅ done — client mode locally, heartbeats on ci |
| play an activity | ⚠️ experimental (`--experimental-activity`), often rejected |
| stream a game | ❌ impossible to fake — skipped |
| earn an achievement | ❌ impossible / riskiest — skipped |

## 🍏 troubleshooting

| problem | fix |
|---|---|
| `401 unauthorized` | token wrong or expired — grab a fresh one |
| workflow does nothing | check the actions log; missing `TOKEN` prints setup steps |
| schedule stopped | github disables it after 60 idle days — push a commit |
| game quest no progress (local) | discord desktop must be open + quest visible in your quests page |
| claim hits a captcha | claim manually in the discord app |
| everything broke overnight | discord changed its private api (happens) — run `python main.py --dump quests.json` and compare |

## 🍎 credits

built on endpoint research from
[orion](https://github.com/nyxxbit/discord-quest-completer) and the
[github-actions selfbot architecture](https://github.com/aiko-chan-ai/Discord-Quest-Auto-Completion-Selfbot)
by aiko-chan-ai, descending from [aamiaa's gist](https://gist.github.com/aamiaa/204cd9d42013ded9faf646fae7f89fbb).
quest icons and names belong to discord; this project is not affiliated with them.

---

<div align="center">

*made with 🍎 by apple-ish*

</div>
