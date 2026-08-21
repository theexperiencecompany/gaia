<div align="center">

# GAIA

**The open-source AI assistant that works for you.**

[![Documentation](https://img.shields.io/badge/Documentation-00bbff?style=flat&logo=gitbook&logoColor=white)](https://docs.heygaia.io) [![Discord](https://discord-live-members-count-badge.vercel.app/api/discord-members?guildId=585464664650022914&color=5c6af3&label=Discord)](https://discord.heygaia.io) [![WhatsApp](https://img.shields.io/badge/WhatsApp-25D366?logo=whatsapp&logoColor=fff&style=flat)](https://whatsapp.heygaia.io) [![Status](https://uptime.betterstack.com/status-badges/v3/monitor/1zjmp.svg)](https://uptime.betterstack.com/?utm_source=status_badge) [![License](https://img.shields.io/badge/license-PolyForm%20NC-121212?style=flat)](LICENSE.md)

<a href="https://heygaia.io"><img src="apps/web/public/images/readme/cta-try-gaia-free.png" alt="Try GAIA Free" height="48" /></a>
<a href="https://docs.heygaia.io/self-hosting/overview"><img src="apps/web/public/images/readme/cta-self-host.png" alt="Self-host" height="48" /></a>

</div>

Most AI assistants wait for you to open a tab and type. You do the work of driving it.

GAIA works the other way round. Connect your Gmail and it starts triaging your inbox every morning, drafting your replies, and turning emails into todos — on its own, from day one. Connect your calendar and it briefs you before every meeting.

When something needs you, it texts you. iMessage, WhatsApp, Telegram, Slack, or Discord.

**Sign up and it's already working.** Nothing to configure.

## Choose a starting point

| If you want to… | Go here |
| --- | --- |
| Just use it | **[heygaia.io](https://heygaia.io)** — sign up, nothing to install |
| Text it from your phone | [iMessage](https://docs.heygaia.io/guides/imessage-bot) · [WhatsApp](https://wa.me/12762088737) · [Telegram](https://t.me/heygaia_bot) · [Slack](https://heygaia.io/slack-bot) · [Discord](https://heygaia.io/discord-bot) |
| Run it on your own machines | `npm i -g @heygaia/cli && gaia init` — or the [guide](https://docs.heygaia.io/self-hosting/overview) |
| Contribute | [Development Setup](https://docs.heygaia.io/developers/development-setup) |
| See how it's built | [ARCHITECTURE.md](./ARCHITECTURE.md) |

## What GAIA does

### Works while you're away

Connect a tool and GAIA sets itself up. No setup screen, no template to pick — the [workflows](#workflows-the-part-that-runs-itself) are already running.

- Watches your tools and tells you when something matters
- Runs jobs on a schedule, in the background
- Its todos aren't reminders — they research and finish themselves
- Reaches you wherever you actually read your messages

### Remembers you

- Learns as you talk — you never have to say "remember this"
- Keeps the people, projects and preferences that come up, plus a journal of recent days
- All of it visible on the **Memory** page as a list or a graph
- Edit, export or delete any of it in a click

### Listens

- Say **"Hey GAIA"** and start talking
- The wake word runs on your device — no audio leaves your machine until you say it
- Calls are real-time and interruptible, with background noise filtered out

### Puts everything in one place

- Your **inbox**, **calendar**, **todos** and **workflows**, with a **dashboard** over the top
- Whatever GAIA did while you were gone waits in **notifications** — approve it, edit it, or dismiss it

### Is yours to run

- Self-host with your own API keys and your own choice of models
- No usage caps, and your data stays on your disks
- Monitoring included, so you can see exactly what it's doing

## Things people actually ask it

- **"Summarize my 47 unread emails and draft replies for the 3 that need one."** Reads every thread end to end, ranks by what matters, drafts in your voice.
- **"Watch my inbox for anything from our investor and ping me on Telegram."** Runs for weeks without you thinking about it. You get a text within the minute.
- **"When my 2pm gets cancelled, rewrite my todo list to use the freed time."** Notices the change itself and replans your afternoon.
- **"Post a Friday digest of my GitHub, Linear and Slack activity to #eng-updates."** Merged PRs, closed issues, channel highlights — gathered, written up, posted.
- **"Before my 1:1 with Alex, brief me on what we shipped this sprint."** Pulls the PRs, issues and threads into one prep doc, ready before you sit down.
- **"Clean up this CSV, chart the outliers, and send me the deck."** Writes real Python, runs it in a real sandbox, hands back a real `.pptx`.

## Workflows: the part that runs itself

A workflow is a job GAIA does without you. Some are already running the moment you connect a tool.

| Workflow | Turns on with | What it does |
| --- | --- | --- |
| **Inbox Triage** | Gmail | Every morning at 8, sorts the last day's mail, pulls out action items, creates the todos, and hands you one briefing |
| **Auto-Draft Replies** | Gmail | Spots mail that needs an answer and writes the reply. You approve before anything sends |
| **Meeting Briefing** | Calendar | Researches who you're meeting and what it's about, before you walk in |
| **Meeting Reminder** | Calendar | A heads-up 10 minutes out, join link included |

Build your own from the **Workflows** page:

- **Describe it in plain English** — GAIA writes the steps for you
- **Run it on a schedule** — "every weekday at 9am"
- **Or on an event** — new email, calendar change, Slack message, GitHub commit, Linear issue, Notion edit, new row in a sheet
- **Chain steps across tools** — fetch, summarise, post to Slack

## Use GAIA from anywhere

| | Platform | How |
| --- | --- | --- |
| <img src="apps/web/public/images/icons/macos/imessage.webp" width="26" height="26" /> | **iMessage** | [Register your number](https://heygaia.io/settings/linked-accounts), text `/auth`, then just type. Pro plan. |
| <img src="apps/web/public/images/icons/macos/whatsapp.webp" width="26" height="26" /> | **WhatsApp** | [Message GAIA](https://wa.me/12762088737) |
| <img src="apps/web/public/images/icons/macos/telegram.webp" width="26" height="26" /> | **Telegram** | [@heygaia_bot](https://t.me/heygaia_bot) — DMs, or `@mention` it in groups |
| <img src="apps/web/public/images/icons/macos/slack.webp" width="26" height="26" /> | **Slack** | [Add to your workspace](https://heygaia.io/slack-bot) |
| <img src="apps/web/public/images/icons/macos/discord.webp" width="26" height="26" /> | **Discord** | [Add the bot](https://heygaia.io/discord-bot) or [join the server](https://discord.heygaia.io) |

- Also on the **web**, a **[desktop app](https://heygaia.io/download)** for macOS, Windows and Linux, and **mobile**
- It's all one account — a chat you start on Telegram shows up in the web app
- Same memory everywhere, no matter where you talk to it

## Connect anything

- **The popular ones, one click.** Gmail, Calendar, Slack, Notion, Linear, GitHub, Sheets, Todoist, Trello, HubSpot and ~20 more. Each gets its own specialist agent.
- **Anything else, via MCP.** Point GAIA at any MCP server and its tools work immediately. No fixed catalogue, no waiting on us to build an integration.
- **A marketplace.** Browse what the community published, or publish your own.
- **Tools on your own computer.** `gaia bridge` links your laptop over one outgoing connection — nothing to forward, no ports to open.

```bash
gaia bridge login          # approve the pairing in your browser
gaia bridge fs ~/projects  # share a folder
gaia bridge up             # connect
```

## It's not just chat

- **It writes and runs real code.** Every user gets a sandboxed Linux workspace. GAIA can analyse a dataset, run the script, and hand you the result — as a PDF, Word doc, deck, or spreadsheet.
- **It researches properly.** Multi-source web research, not a single search box.
- **It learns new abilities.** 37 built-in skills using the open [Agent Skills spec](https://agentskills.io), plus any skill you install from GitHub or write yourself.
- **It's model-agnostic.** OpenAI, Gemini, Grok, and OpenRouter — which covers Claude and most everything else. Self-hosters can swap freely.

## Getting started

### Cloud — recommended

<a href="https://heygaia.io"><img src="apps/web/public/images/screenshots/website_tab.png" alt="GAIA web app" width="500" /></a>

Go to **[heygaia.io](https://heygaia.io)**. Free, nothing to install, always up to date.

This is how most people should use GAIA — you skip running six databases yourself.

### Self-host

<a href="https://heygaia.io/install"><img src="apps/web/public/images/screenshots/cli.png" alt="GAIA CLI" width="500" /></a>

Prefer your own machines? You get your own keys and models, no caps, and your data on your disks — in exchange for running real infrastructure.

Needs [Docker](https://docs.docker.com/get-docker/) (Engine 20.10+, Compose v2+) and [Node.js](https://nodejs.org) 20+.

```bash
npm install -g @heygaia/cli
gaia init                     # choose "Self-Host (Docker)"
# → http://localhost:3000
```

That checks prerequisites, clones the repo, walks you through the environment variables, then builds and starts everything. After that:

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

<details>
<summary><b>How the agent system works</b></summary>

<br />

GAIA runs three tiers of agents. The one you talk to never does the work itself — it hands off, so the conversation stays responsive while long jobs run in the background.

```
  Comms agent        Talks to you and narrates progress. Deliberately
      │              cannot do work — it can only delegate.
      ▼  call_executor(task)   →  returns instantly, runs in background
  Executor agent     The worker. Shell, files, research, planning, todos,
      │              and the handoff tool.
      ▼  handoff(subagent, task)
  Subagents          One specialist per integration, dispatched in parallel,
                     each scoped to only its own tools.
```

Why bother: a single agent holding 30 integrations' worth of tools picks the wrong one and gets slower with every tool you add. Scoping each integration to its own agent keeps tool choice accurate, and running them in parallel keeps it fast.

Every service and file path is mapped in **[ARCHITECTURE.md](./ARCHITECTURE.md)**.

</details>

## Roadmap

We build in the open. **[View the roadmap](https://gaia.featurebase.app/roadmap)** · **[Request a feature](https://gaia.featurebase.app)**

## FAQ

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
