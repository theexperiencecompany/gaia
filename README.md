<div align="center">

# GAIA

**The open-source AI assistant that works while you don't.**

[![Documentation](https://img.shields.io/badge/Documentation-00bbff?style=flat&logo=gitbook&logoColor=white)](https://docs.heygaia.io) [![Discord](https://discord-live-members-count-badge.vercel.app/api/discord-members?guildId=585464664650022914&color=5c6af3&label=Discord)](https://discord.heygaia.io) [![WhatsApp](https://img.shields.io/badge/WhatsApp-25D366?logo=whatsapp&logoColor=fff&style=flat)](https://whatsapp.heygaia.io) [![Status](https://uptime.betterstack.com/status-badges/v3/monitor/1zjmp.svg)](https://uptime.betterstack.com/?utm_source=status_badge) [![License](https://img.shields.io/badge/license-PolyForm%20NC-121212?style=flat)](LICENSE.md)

<a href="https://heygaia.io"><img src="apps/web/public/images/readme/cta-try-gaia-free.png" alt="Try GAIA Free" height="48" /></a>
<a href="https://docs.heygaia.io/self-hosting/overview"><img src="apps/web/public/images/readme/cta-self-host.png" alt="Self-host" height="48" /></a>

</div>

Most AI assistants wait for you to open a tab and type. GAIA doesn't. It connects to the tools you already use, watches for the things you told it to care about, does the work in the background, and messages you on WhatsApp, Telegram, Slack, or Discord when there's something you actually need to see.

It remembers you between conversations, it can write and run real code in a sandbox, you can talk to it out loud, and you can run the entire thing on your own hardware.

```bash
npm install -g @heygaia/cli && gaia init
```

## Choose a starting point

| If you want to… | Start here |
| --- | --- |
| Just use it, zero setup | **[heygaia.io](https://heygaia.io)** — sign up and start |
| Text it from your phone | [WhatsApp](https://wa.me/12762088737) · [Telegram](https://t.me/heygaia_bot) · [Slack](https://heygaia.io/slack-bot) · [Discord](https://heygaia.io/discord-bot) |
| Run it on your own machines | [Self-Hosting Guide](https://docs.heygaia.io/self-hosting/overview) — or `gaia init` above |
| Give it access to your local files and tools | [`gaia bridge`](#bring-your-own-machine) — outbound-only, no ports to open |
| Understand how it's built | [Architecture](#how-it-works) · [ARCHITECTURE.md](./ARCHITECTURE.md) |
| Contribute | [Development Setup](https://docs.heygaia.io/developers/development-setup) · [Contributing](https://docs.heygaia.io/developers/contributing) |

## Why GAIA

We all drown in tools. Gmail, Calendar, Todos, Docs, Slack, Linear, WhatsApp — different stacks, same problem. Our days are eaten by small repetitive actions that aren't real work. Each one feels trivial, but together they drain focus. Inboxes clog, todo lists rot, and important things slip through.

Most automation doesn't fix this. It's rigid, built for power users, and asks you to re-explain your context every single time. A real assistant should already know you — how you write, who you work with, what you ignore.

Four things make GAIA that, and they're worth reading in order.

### It acts before you ask

This is the whole point, and it's not a personality trait — it's machinery you can inspect:

- **Event triggers.** Real webhook subscriptions across 10 services — a new Gmail message, a calendar event created or starting soon, a Slack message or new channel, a GitHub commit/PR/issue/star, a Linear issue or comment, a Notion page update, new rows in a Sheet, a new Google Doc, a Todoist or Asana task. Not polling from a laptop that has to stay open.
- **Scheduled workflows.** Cron-style, timezone-aware. "Every Monday at 9am, scan my calendar and prep a briefing for each meeting."
- **Self-executing todos.** Tracked todos don't just remind you — they run. They research, draft, and complete themselves, with a durable canvas that persists across conversations.
- **Background sweeps.** A worker tier handles reminders, memory backfill, and maintenance on its own schedule — including auto-pausing workflows for inactive users so nothing runs up a bill in the dark.
- **Then it finds you.** When a run produces something you should see — a drafted reply, a new todo, a suggested event — it routes to the notification bell, your email, or straight to whichever chat app you actually read.

### It remembers you

Not a chat log, and not flat vector recall. GAIA runs a Postgres-backed memory engine with three layers: **facts** (people, projects, preferences), a rolling **journal** of recent episodes, and long-form **documents**. Chroma handles semantic retrieval; dedicated consolidation and reconciliation passes keep it from rotting into contradictions.

It learns passively — a memory hook runs at the end of every turn, so things you mention in passing become durable without you calling a tool. The whole store is projected to Markdown files the agent can read directly, and to a memory graph in the UI you can browse, edit, export as PNG/SVG, or delete outright.

### It's wherever you are

Web, desktop (macOS, Windows, Linux), mobile, and four chat platforms — all one assistant with one memory, not four disconnected bots. Plus:

- **Voice.** A real-time voice agent on LiveKit — Deepgram STT, ElevenLabs TTS, Silero VAD, multilingual turn detection, and noise cancellation.
- **"Hey GAIA."** A wake word that runs **entirely on-device**. A custom-trained ONNX classifier on an openWakeWord pipeline (mel → embedding → VAD → classifier), shipping for web, Electron, and React Native. No audio leaves your machine until you say the words.

### It's actually yours

PolyForm Noncommercial, self-hostable end to end, and honest about the boundary: there's no separate "enterprise edition" holding back the good parts. Self-hosting means your own keys, your own models, no usage caps, and your data on your own disks.

## What people actually ask it

Every example below works today.

- **"Summarize the 47 unread emails in my inbox and draft replies for the 3 that need one."** Ranks by importance, reads threads end to end, writes drafts in your voice.
- **"Watch my email for anything from [investor] and ping me on Telegram within 60 seconds."** Persistent background monitoring, cross-channel notification.
- **"When my 2pm gets cancelled, rewrite my todo list to use the freed time."** Watches calendar changes and replans the afternoon against your pending todos.
- **"Pull my GitHub, Linear, and Slack activity this week and post a Friday digest to #eng-updates."** Merged PRs, closed issues, channel highlights — gathered, formatted, posted.
- **"Before my 1:1 with Alex tomorrow, brief me on everything we shipped this sprint."** PRs, Linear issues, and Slack threads into one prep doc.
- **"Turn this transcript into action items, assign owners, and add them to Linear."** Extracts decisions, matches them to projects, creates issues.
- **"Research these 10 companies into a table with pricing, team size, and funding."** Web research, structured output, ready to paste.
- **"Clean up this CSV, chart the outliers, and send me the deck."** Real Python in a real sandbox, then a real `.pptx` back.

## Reach GAIA anywhere

| | Platform | How |
| --- | --- | --- |
| <img src="apps/web/public/images/icons/macos/whatsapp.webp" width="28" height="28" /> | **WhatsApp** | [Message GAIA](https://wa.me/12762088737) — chat normally or use `/gaia` |
| <img src="apps/web/public/images/icons/macos/telegram.webp" width="28" height="28" /> | **Telegram** | [@heygaia_bot](https://t.me/heygaia_bot) — DMs or `@mention` in groups |
| <img src="apps/web/public/images/icons/macos/slack.webp" width="28" height="28" /> | **Slack** | [Add to workspace](https://heygaia.io/slack-bot) — `/gaia` and slash commands |
| <img src="apps/web/public/images/icons/macos/discord.webp" width="28" height="28" /> | **Discord** | [Add the bot](https://heygaia.io/discord-bot) or [join the server](https://discord.heygaia.io) |
| 🌐 | **Web & Desktop** | [heygaia.io](https://heygaia.io) · [Download](https://heygaia.io/download) for macOS, Windows, Linux |
| 📱 | **Mobile** | React Native app (beta) |
| 🎙️ | **Voice** | Talk to it live, or just say **"Hey GAIA"** |
| <img src="apps/web/public/images/icons/macos/imessage.svg" width="28" height="28" /> | **iMessage** | *Coming soon* |

Every surface shares one conversation history and one memory. Start a task on desktop, get the answer on Telegram.

## Integrations

Around 30 services connect in one click, each with its own specialist subagent rather than one agent fumbling through a giant tool list.

| | |
| --- | --- |
| **Google** | Gmail · Calendar · Docs · Sheets · Tasks · Meet · Maps |
| **Work** | Slack · Notion · Linear · GitHub · Microsoft Teams · Zoom · Airtable |
| **Tasks** | Todoist · Asana · ClickUp · Trello |
| **Social** | Twitter/X · LinkedIn · Reddit · Instagram |
| **Business** | HubSpot · PostHog |
| **Research** | Perplexity · Context7 · DeepWiki · Hacker News · Browserbase |
| **Life** | Instacart · Yelp |

Not in the list? Add **any MCP server** from the same page — connect it privately or publish it to the community marketplace.

### Bring your own machine

`gaia bridge` pairs a local machine to your GAIA account over an **outbound-only WebSocket** — no inbound ports, no tunnel service, no firewall changes. From there you can expose local MCP servers or specific folders to your assistant.

```bash
gaia bridge login          # RFC 8628 device pairing, approve in the browser
gaia bridge fs ~/projects  # expose a folder
gaia bridge up             # connect
```

## How it works

GAIA runs a three-tier agent system. The agent you talk to never does the work itself — it delegates, so the conversation stays responsive while long jobs run in the background.

```
  Comms agent          talks to you, narrates progress, owns the thread
      │                tiny tool surface — it cannot do work itself
      ▼  call_executor(task)  →  returns immediately, runs in background
  Executor agent       the worker tier: bash, files, research, planning,
      │                todos, and the handoff tool
      ▼  handoff(subagent, task, background=…)
  Subagents            one specialist graph per integration, dispatched in
                       parallel, each scoped to just its own tools
```

Underneath that:

- **A real computer.** `bash`, `read`, `write`, `edit`, `grep` run in a per-user E2B sandbox on a JuiceFS-backed workspace. GAIA can write code, run it, and hand you the artifact — PDF, DOCX, PPTX, spreadsheets, charts.
- **Skills.** 37 built-in skills following the open [Agent Skills spec](https://agentskills.io) — folders of `SKILL.md` plus scripts, loaded into the workspace at runtime. Install more straight from any GitHub repo, or write your own.
- **Deep research.** Multi-query, multi-source web research with a self-hosted SearXNG in the stack.
- **Full MCP client.** Remote servers with OAuth discovery and token management, plus local servers over the device bridge.
- **Models.** OpenAI, Gemini, Grok, and OpenRouter (which is how Claude and most others get in). The catalog is database-driven, so self-hosters can swap freely.

For the full map — every file path, every service — see **[ARCHITECTURE.md](./ARCHITECTURE.md)**.

## Getting started

> **Just want to use it?** Cloud. **Care where your data lives, or want your own keys and no caps?** Self-host. The interface is identical.

### Cloud (recommended)

Visit **[heygaia.io](https://heygaia.io)** — no installation, free to start.

### Self-hosting

One CLI sets up the whole stack. **Prerequisites:** [Docker](https://docs.docker.com/get-docker/) (Engine 20.10+, Compose v2+) and [Node.js](https://nodejs.org) 20+.

```bash
npm install -g @heygaia/cli   # pnpm add -g / bun add -g also work
gaia init                     # pick "Self-Host (Docker)" when asked
# → http://localhost:3000
```

`gaia init` checks prerequisites, clones the repo, walks you through environment variables, then builds and starts everything in Docker.

```bash
gaia status   # health-check every service
gaia logs     # stream logs
gaia stop     # stop everything
gaia start    # bring it back up
```

Already cloned? Run `gaia setup` inside the checkout. Contributing? Choose **"Developer"** in `gaia init` for hot-reload local dev.

Self-hosting runs Postgres, MongoDB, Redis, ChromaDB, RabbitMQ, and SearXNG alongside the apps. A single modestly-sized VM handles a small team; the real cost is model API usage. Details in the [Self-Hosting Guide](https://docs.heygaia.io/self-hosting/overview).

## Repository

Full-stack Nx monorepo.

```
apps
├── web            Next.js web app                       heygaia.io
├── desktop        Electron desktop app (beta)
├── mobile         React Native mobile app (beta)
├── api            FastAPI + LangGraph backend
├── voice-agent    LiveKit voice worker
├── bridge         gaia bridge — local MCP/file tunnel
└── bots           discord · slack · telegram · whatsapp
packages
├── cli            @heygaia/cli
└── gaia-ui        @heygaia/ui
libs
├── shared/py      gaia-shared (api, voice-agent)
├── shared/ts      shared TypeScript + unified bot framework
└── wake-word      @gaia/wake-word — on-device "Hey GAIA"
docs               docs.heygaia.io
infra/docker       Docker Compose (dev + prod)
```

**Stack** — Next.js 16 / React 19 / Tailwind / Zustand / HeroUI · Electron · React Native + Expo · FastAPI / Python 3.11+ / Pydantic · LangGraph · LiveKit + Deepgram + ElevenLabs · Composio · E2B · Postgres / MongoDB / Redis / ChromaDB · RabbitMQ + ARQ · Prometheus / Grafana / Loki / Sentry / PostHog · Nx / pnpm / uv / mise / Biome / Ruff.

## Roadmap

We build in the open. **[View the roadmap](https://gaia.featurebase.app/roadmap)** · **[Request a feature](https://gaia.featurebase.app)**

## FAQ

<details>
<summary><b>How does GAIA's proactive behaviour actually work?</b></summary>

Go to the **Workflows** page and build one. Two kinds of triggers:

- **Scheduled** — cron-style, timezone-aware ("every weekday at 9am", "first Monday of the month")
- **Event-driven** — real webhook subscriptions on Gmail, Google Calendar, Google Sheets, Google Docs, Slack, GitHub, Linear, Notion, Todoist, and Asana

Chain steps across integrations ("fetch → summarise → post to Slack") and GAIA runs the whole thing in the background with no prompt. When a run produces something you should see, it lands in the notifications bell and on `/notifications`, where you can approve, edit, or dismiss it — and it can be pushed to your connected chat app too.

</details>

<details>
<summary><b>What data does GAIA store about me, and can I delete it?</b></summary>

All of it is under your control:

- **Memory** — everything GAIA has learned is visible on the **Memory** settings page as a list or interactive graph. Delete individual memories or clear everything in one click. Export the graph as PNG or SVG.
- **Chat history** — one-click "Clear chat history" in **Preferences**.
- **Workflows, todos, reminders** — managed from their own pages.
- **Integration tokens** — stored encrypted, revoked immediately on disconnect.

Integration content — email bodies, calendar events, documents — is never persisted. It's fetched on demand when a request needs it.

</details>

<details>
<summary><b>Does GAIA read my email?</b></summary>

Only threads relevant to what you asked it to do, and only within the scopes you granted on Google's consent screen when you connected Gmail. Email content isn't mirrored into GAIA's database — it's fetched per request. Disconnect from `/integrations` at any time to revoke access immediately.

</details>

<details>
<summary><b>Can I bring my own API keys and models?</b></summary>

**Self-hosted:** yes. Model providers and integration services are configured via environment variables, and the model catalog is database-driven, so you can swap freely.

**Cloud:** no — the platform manages models for you and usage is governed by your plan. You can still choose between available models in the chat composer.

</details>

<details>
<summary><b>How do I connect a new integration?</b></summary>

Open `/integrations`. Browse by category or search. Click **Connect** — OAuth providers redirect to their consent screen, API-key providers pop a modal. The sidebar then shows the tools that integration unlocks, and **Disconnect** revokes access in one click.

Need something not in the catalogue? Add your own MCP server from the same page, keep it private, or publish it to the community marketplace.

</details>

<details>
<summary><b>What does self-hosting cost to run?</b></summary>

The code is free under PolyForm Noncommercial. Real costs are model API usage (scales with use), any paid integration services you opt into, and hosting — a single modestly-sized VM handles a small team. See the [self-hosting guide](https://docs.heygaia.io/self-hosting/overview) for numbers.

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

> 🤖 **AI and vibe-coded PRs are welcome.** Built it with Claude, Cursor, or anything else? Great — just mention it in the PR description.

[Contributing Guidelines](https://docs.heygaia.io/developers/contributing) · [Development Setup](https://docs.heygaia.io/developers/development-setup) · [Code Style](https://docs.heygaia.io/configuration/code-style) · [Conventional Commits](https://docs.heygaia.io/configuration/conventional-commits) · [Pull Requests](https://docs.heygaia.io/configuration/pull-requests)

For bugs and feature requests, [open an issue](https://github.com/theexperiencecompany/gaia/issues).

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
