<div align="center">

# GAIA

**The open-source AI assistant that works while you don't.**

[![Documentation](https://img.shields.io/badge/Documentation-00bbff?style=flat&logo=gitbook&logoColor=white)](https://docs.heygaia.io) [![Discord](https://discord-live-members-count-badge.vercel.app/api/discord-members?guildId=585464664650022914&color=5c6af3&label=Discord)](https://discord.heygaia.io) [![WhatsApp](https://img.shields.io/badge/WhatsApp-25D366?logo=whatsapp&logoColor=fff&style=flat)](https://whatsapp.heygaia.io) [![Status](https://uptime.betterstack.com/status-badges/v3/monitor/1zjmp.svg)](https://uptime.betterstack.com/?utm_source=status_badge) [![License](https://img.shields.io/badge/license-PolyForm%20NC-121212?style=flat)](LICENSE.md)

<a href="https://heygaia.io"><img src="apps/web/public/images/readme/cta-try-gaia-free.png" alt="Try GAIA Free" height="48" /></a>
<a href="https://docs.heygaia.io/self-hosting/overview"><img src="apps/web/public/images/readme/cta-self-host.png" alt="Self-host" height="48" /></a>

</div>

Most AI assistants wait for you to open a tab and type.

GAIA doesn't. It connects to the tools you already use, watches for the things you told it to care about, and does the work in the background. When something needs you, it texts you — on iMessage, WhatsApp, Telegram, Slack, or Discord.

It remembers you between conversations. You can talk to it out loud. And you can run the whole thing on your own hardware.

## Choose a starting point

| If you want to… | Go here |
| --- | --- |
| Just use it | **[heygaia.io](https://heygaia.io)** — sign up, nothing to install |
| Text it from your phone | [iMessage](https://docs.heygaia.io/guides/imessage-bot) · [WhatsApp](https://wa.me/12762088737) · [Telegram](https://t.me/heygaia_bot) · [Slack](https://heygaia.io/slack-bot) · [Discord](https://heygaia.io/discord-bot) |
| Run it on your own machines | `npm i -g @heygaia/cli && gaia init` — or the [guide](https://docs.heygaia.io/self-hosting/overview) |
| Contribute | [Development Setup](https://docs.heygaia.io/developers/development-setup) |
| See how it's built | [ARCHITECTURE.md](./ARCHITECTURE.md) |

## What GAIA does

### It works while you're away

This is the whole point. Four things drive it:

- **It watches your tools.** Real webhook subscriptions on Gmail, Calendar, Slack, GitHub, Linear, Notion, Sheets, Docs, Todoist, and Asana. A new email arrives, a meeting gets moved, an issue gets assigned — GAIA knows.
- **It runs on a schedule.** "Every Monday at 9am, prep a briefing for each meeting on my calendar."
- **Its todos do themselves.** Tracked todos don't just remind you. They research, draft, and finish the work.
- **Then it finds you.** Something worth seeing gets sent to you — in the app, by email, or straight to whichever chat app you actually read.

### It remembers you

Tell it once. It sticks.

GAIA keeps facts about you (people, projects, preferences), a running journal of recent days, and longer documents you've built up together. It learns as you talk, so you never have to say "remember this."

You own all of it. The **Memory** page shows everything as a list or an interactive graph — edit it, export it, or delete any of it in a click.

### You can just talk to it

Say **"Hey GAIA"** and start talking. The wake word runs entirely on your device, so no audio leaves your machine until you say it.

Voice calls are real-time and interruptible, with natural turn-taking and background noise filtered out.

### It's genuinely yours

Self-host the whole stack with your own keys, your own models, and no usage caps. There's no "enterprise edition" holding back the good parts.

## Things people actually ask it

Every one of these works today.

- *"Summarize my 47 unread emails and draft replies for the 3 that need one."*
- *"Watch my inbox for anything from [investor] and ping me on Telegram within 60 seconds."*
- *"When my 2pm gets cancelled, rewrite my todo list to use the freed time."*
- *"Post a Friday digest of my GitHub, Linear, and Slack activity to #eng-updates."*
- *"Before my 1:1 with Alex, brief me on everything we shipped this sprint."*
- *"Turn this transcript into action items, assign owners, and add them to Linear."*
- *"Research these 10 companies into a table with pricing, team size, and funding."*
- *"Clean up this CSV, chart the outliers, and send me the deck."*

## Text GAIA from anywhere

| | Platform | How |
| --- | --- | --- |
| <img src="apps/web/public/images/icons/macos/imessage.webp" width="26" height="26" /> | **iMessage** | [Register your number](https://heygaia.io/settings/linked-accounts), text `/auth`, then just type. Pro plan. |
| <img src="apps/web/public/images/icons/macos/whatsapp.webp" width="26" height="26" /> | **WhatsApp** | [Message GAIA](https://wa.me/12762088737) |
| <img src="apps/web/public/images/icons/macos/telegram.webp" width="26" height="26" /> | **Telegram** | [@heygaia_bot](https://t.me/heygaia_bot) — DMs, or `@mention` it in groups |
| <img src="apps/web/public/images/icons/macos/slack.webp" width="26" height="26" /> | **Slack** | [Add to your workspace](https://heygaia.io/slack-bot) |
| <img src="apps/web/public/images/icons/macos/discord.webp" width="26" height="26" /> | **Discord** | [Add the bot](https://heygaia.io/discord-bot) or [join the server](https://discord.heygaia.io) |

There's also a web app, a desktop app for macOS, Windows and Linux, and a mobile app.

It's one assistant everywhere, not six disconnected bots. Start something on your laptop, get the answer on your phone.

## Connect anything

**One click for the popular ones.** Gmail, Calendar, Slack, Notion, Linear, GitHub, Sheets, Todoist, Trello, HubSpot and about 20 more. Connect from `/integrations` and GAIA gets a dedicated specialist for that tool.

**Anything else, via MCP.** GAIA is a full Model Context Protocol client. Point it at any MCP server and those tools work immediately. There's no fixed catalogue and no waiting for us to build an integration.

**Tools on your own computer.** Want GAIA to work with files or local tools on your laptop? `gaia bridge` links your machine to your account over one outgoing connection. Nothing to forward, no ports to open on your firewall.

```bash
gaia bridge login          # approve the pairing in your browser
gaia bridge fs ~/projects  # share a folder
gaia bridge up             # connect
```

**A marketplace.** Browse what the community has published, or publish your own.

## It's not just chat

- **It writes and runs real code.** Every user gets a sandboxed Linux workspace. GAIA can analyse a dataset, run the script, and hand you the result — as a PDF, Word doc, deck, or spreadsheet.
- **It researches properly.** Multi-source web research, not a single search box.
- **It learns new abilities.** 37 built-in skills using the open [Agent Skills spec](https://agentskills.io), plus any skill you install from GitHub or write yourself.
- **It's model-agnostic.** OpenAI, Gemini, Grok, and OpenRouter — which covers Claude and most everything else. Self-hosters can swap freely.

## Getting started

> **Just want to use it?** Use the cloud. **Care where your data lives, or want your own keys and no caps?** Self-host. The app is identical either way.

### Cloud

<a href="https://heygaia.io"><img src="apps/web/public/images/screenshots/website_tab.png" alt="GAIA web app" width="500" /></a>

Go to **[heygaia.io](https://heygaia.io)**. Free to start, nothing to install.

### Self-host

<a href="https://heygaia.io/install"><img src="apps/web/public/images/screenshots/cli.png" alt="GAIA CLI" width="500" /></a>

One command sets up the whole stack. You'll need [Docker](https://docs.docker.com/get-docker/) (Engine 20.10+, Compose v2+) and [Node.js](https://nodejs.org) 20+.

```bash
npm install -g @heygaia/cli
gaia init                     # choose "Self-Host (Docker)"
# → http://localhost:3000
```

`gaia init` checks your prerequisites, clones the repo, walks you through the environment variables, then builds and starts everything.

```bash
gaia status   # health-check every service
gaia logs     # stream logs
gaia stop     # stop everything
gaia start    # bring it back up
```

Already cloned the repo? Run `gaia setup` inside it. Contributing? Choose **"Developer"** for hot-reload local dev.

A single modest VM handles a small team. The real cost is model API usage — see the [self-hosting guide](https://docs.heygaia.io/self-hosting/overview) for numbers.

## Repository

Full-stack Nx monorepo.

```
apps
├── web            Next.js web app                    heygaia.io
├── desktop        Electron desktop app (beta)
├── mobile         React Native mobile app (beta)
├── api            FastAPI + LangGraph backend
├── voice-agent    LiveKit voice worker
├── bridge         gaia bridge — local file/tool tunnel
└── bots           imessage · whatsapp · telegram · slack · discord
packages
├── cli            @heygaia/cli
└── gaia-ui        @heygaia/ui
libs
├── shared/py      gaia-shared
├── shared/ts      shared TypeScript + the unified bot framework
└── wake-word      @gaia/wake-word — on-device "Hey GAIA"
docs               docs.heygaia.io
infra/docker       Docker Compose (dev + prod)
```

How the agent system actually fits together — every service, every file path — is in **[ARCHITECTURE.md](./ARCHITECTURE.md)**.

## Roadmap

We build in the open. **[View the roadmap](https://gaia.featurebase.app/roadmap)** · **[Request a feature](https://gaia.featurebase.app)**

## FAQ

<details>
<summary><b>How does the proactive part actually work?</b></summary>

Open the **Workflows** page and build one. There are two kinds of triggers:

- **Scheduled** — cron-style and timezone-aware ("every weekday at 9am")
- **Event-driven** — real webhook subscriptions on Gmail, Google Calendar, Sheets, Docs, Slack, GitHub, Linear, Notion, Todoist, and Asana

Chain steps across your tools ("fetch → summarise → post to Slack") and GAIA runs the whole thing in the background with no prompt from you.

When a run produces something you should see, it lands in your notifications — where you can approve, edit, or dismiss it — and can be pushed to your chat app too.

</details>

<details>
<summary><b>What does GAIA store about me, and can I delete it?</b></summary>

All of it is under your control:

- **Memory** — see everything on the Memory page as a list or graph. Delete individual items or clear it all. Export as PNG or SVG.
- **Chat history** — one-click clear in Preferences.
- **Workflows, todos, reminders** — managed from their own pages.
- **Integration tokens** — encrypted, and revoked the moment you disconnect.

Your actual content — email bodies, calendar events, documents — is never copied into GAIA's database. It's fetched when a request needs it and not kept.

</details>

<details>
<summary><b>Does GAIA read my email?</b></summary>

Only the threads relevant to what you asked it to do, and only within the scopes you granted on Google's consent screen. Nothing is mirrored into a database. Disconnect from `/integrations` and access is revoked immediately.

</details>

<details>
<summary><b>Can I use my own API keys and models?</b></summary>

**Self-hosted:** yes. Providers are set via environment variables and the model catalogue is database-driven, so you can swap freely.

**Cloud:** no — models are managed for you and usage follows your plan. You can still pick between the available models in the composer.

</details>

<details>
<summary><b>How do I add an integration that isn't in the list?</b></summary>

Add it as an MCP server from `/integrations`. Paste the server URL, connect it privately, and its tools are available right away. You can publish it to the community marketplace if you want to share it.

For tools running on your own machine, use `gaia bridge` instead.

</details>

<details>
<summary><b>What does self-hosting cost?</b></summary>

The code is free under PolyForm Noncommercial. Your real costs are model API usage, any paid integrations you opt into, and hosting. A single modest VM handles a small team. The [self-hosting guide](https://docs.heygaia.io/self-hosting/overview) has numbers.

</details>

## Documentation

**[docs.heygaia.io](https://docs.heygaia.io)** — [Quick Start](https://docs.heygaia.io/quick-start) · [Bots](https://docs.heygaia.io/bots/overview) · [Self-Hosting](https://docs.heygaia.io/self-hosting/overview) · [Developers](https://docs.heygaia.io/developers/introduction)

## Community

- **[Discord](https://discord.heygaia.io)** — chat with the team and other users
- **[Twitter](https://twitter.com/trygaia)** — news and updates
- **[WhatsApp](https://whatsapp.heygaia.io)** — direct support from our team

## Contributing

<a href="https://github.com/theexperiencecompany/gaia/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=theexperiencecompany/gaia" />
</a>

Bug fixes, features, docs, tests — all welcome.

> 🤖 **AI and vibe-coded PRs are welcome.** Built it with Claude, Cursor, or anything else? Great — just say so in the PR description.

[Contributing Guidelines](https://docs.heygaia.io/developers/contributing) · [Development Setup](https://docs.heygaia.io/developers/development-setup) · [Code Style](https://docs.heygaia.io/configuration/code-style) · [Conventional Commits](https://docs.heygaia.io/configuration/conventional-commits) · [Pull Requests](https://docs.heygaia.io/configuration/pull-requests)

Found a bug? [Open an issue](https://github.com/theexperiencecompany/gaia/issues).

## License

[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/) — see [LICENSE.md](LICENSE.md).

> [!WARNING]
> This license allows noncommercial use only.

GAIA is built on the shoulders of giants. Full credits at **[heygaia.io/thanks](https://heygaia.io/thanks)**.

---

<div align="center">

If GAIA could save you even an hour a week, consider giving it a ⭐ — it helps more people find the project.

<a href="https://www.star-history.com/#theexperiencecompany/gaia&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=theexperiencecompany/gaia&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=theexperiencecompany/gaia&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=theexperiencecompany/gaia&type=Date" />
 </picture>
</a>

<br /><br />

Made with ❤️ by [The Experience Company](https://experience.heygaia.io)

[heygaia.io](https://heygaia.io) • [Documentation](https://docs.heygaia.io) • [Contact](https://heygaia.io/contact) • contact@heygaia.io

</div>
