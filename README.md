<div align="center">

# 🍎 EverApple

*keeps your discord status online 24/7 — no pc, no vps, just github*

<img src="https://img.shields.io/badge/status-running%2024%2F7-4caf50?style=for-the-badge&logo=githubactions&logoColor=white" alt="status badge"/>
<img src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="python badge"/>
<img src="https://img.shields.io/badge/license-MIT-red?style=for-the-badge" alt="license badge"/>

</div>

---

> [!WARNING]
> this is a **selfbot** — it automates your discord **user account**, which
> violates the [discord terms of service](https://discord.com/terms). your
> account may be warned or suspended. use an account you can afford to lose.

---

## ✨ what it does

| command | effect |
|:---:|---|
| `a.on` | 🟢 status → **online** (stays forever) |
| `a.off` | 👻 status → **invisible** |
| `a.idle` | 🌙 status → **idle** |
| `a.dnd` | ⛔ status → **do not disturb** |
| `a.status` | 📊 check current status |

- 🕵️ **stealth** — every command message self-destructs instantly
- 🔒 **owner lock** — only your account can trigger commands (`OWNER_ID` secret)
- 💓 **keepalive** — re-asserts presence every 60s so discord can't drop it
- 🔄 **persistence** — survives reconnects, runner restarts, and workflow re-runs

## 🍏 setup (fork & run)

<div align="center">

*fork → secrets → enable actions → run. that's it.*

</div>

**1.** fork this repo

**2.** go to **settings → secrets and variables → actions** and add:

| secret | required | what it is |
|---|:---:|---|
| `DISCORD_TOKEN` | ✅ | your discord user token |
| `OWNER_ID` | recommended | your discord user id (developer mode → right-click name → copy id) |

**3.** open the **actions** tab → enable workflows if prompted

**4.** select **everapple keepalive** → **run workflow**

<div align="center">

🍎 *that's it — your status is now set and kept, forever*

</div>

## 🧺 how persistence works

once you set a status, the selfbot re-asserts it every 60 seconds while running.
the workflow re-launches every 6 hours, and on every fresh start the bot restores
the last status it was told to hold — so your choice survives restarts until you
change it with another command.

## 🍎 license

MIT

---

<div align="center">

*made with 🍎 by apple-ish*

</div>
