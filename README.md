<div align="center">

<img src="apps/desktop/resources/icons/512x512.png" alt="GAIA" width="128" />

# GAIA

**The open-source AI assistant that handles your whole day.**

[![Documentation](https://img.shields.io/badge/Documentation-00bbff?style=flat&logo=gitbook&logoColor=white)](https://docs.heygaia.io) [![Discord](https://discord-live-members-count-badge.vercel.app/api/discord-members?guildId=585464664650022914&color=5c6af3&label=Discord)](https://discord.heygaia.io) [![WhatsApp](https://img.shields.io/badge/WhatsApp-25D366?logo=whatsapp&logoColor=fff&style=flat)](https://whatsapp.heygaia.io)

</div>

GAIA is a personal AI assistant that can automate your whole day. Connect Gmail and it triages your inbox every morning, drafts your replies and turns emails into todos. Connect your calendar and it briefs you before every meeting.

You set none of that up. It's running the moment you connect.

And when something needs you, it comes to you — on iMessage, WhatsApp, Telegram, Slack or Discord.

<div align="center">

<a href="https://heygaia.io/signup"><img src="apps/web/public/images/readme/cta-get-started.webp" alt="Get Started" height="52" /></a>
<a href="https://docs.heygaia.io"><img src="apps/web/public/images/readme/cta-read-the-docs.webp" alt="Read the docs" height="52" /></a>

</div>

<p align="center">Run GAIA on your own machine:</p>

```bash
curl -fsSL https://heygaia.io/install.sh | sh
```

## Why GAIA

Gmail, Calendar, Slack, Notion, Linear — different tools, same problem: your day fills with work that isn't your job. Triaging mail, prepping for meetings, chasing updates, copying tasks between apps. Each one costs two minutes. Together they cost your afternoon.

**GAIA does that layer for you.** It does the work, then tells you when it's done.

## Features

- **Proactive** — connect a tool and jobs start running on their own, no setup
- **Workflows** — automations on a schedule or an event, written for you from plain English
- **Memory** — learns people, projects and preferences as you talk; edit, export or delete any of it
- **Voice** — real-time calls, plus a "Hey GAIA" wake word that runs [on your device](libs/wake-word)
- **Multi-platform** — iMessage, WhatsApp, Telegram, Slack, Discord, web, desktop and mobile, on one account
- **Integrations** — services one click away, or anything with an MCP server
- **Code execution** — a sandboxed workspace that hands back real PDFs, decks and spreadsheets
- **Deep research** — multi-source web research with structured output
- **Browser-use** — drives a real browser to log in, fill forms, click through and finish tasks on any website
- **Skills** — built on the open [Agent Skills spec](https://agentskills.io); install more from GitHub
- **One workspace** — inbox, calendar, todos and notifications in a single app
- **Self-hostable** — open source, your keys, your models, no caps

## Getting started

| If you want to… | Go here |
| --- | --- |
| Just use it | **[heygaia.io](https://heygaia.io)** — sign up, nothing to install |
| Text it from your phone | [iMessage](https://docs.heygaia.io/guides/imessage-bot) · [WhatsApp](https://wa.me/12762088737) · [Telegram](https://t.me/heygaia_bot) · [Slack](https://heygaia.io/slack-bot) · [Discord](https://heygaia.io/discord-bot) |
| Run it on your own machines | `curl -fsSL https://heygaia.io/install.sh \| sh` — or the [guide](https://docs.heygaia.io/self-hosting/walkthrough) |
| Contribute | [Development Setup](https://docs.heygaia.io/developers/development-setup) |
| See how it's built | [ARCHITECTURE.md](./ARCHITECTURE.md) |

### Cloud — recommended

<a href="https://heygaia.io"><img src="apps/web/public/images/readme/cloud.webp" alt="heygaia.io open in a browser tab" width="720" /></a>

Go to **[heygaia.io](https://heygaia.io)**. Nothing to install, always up to date.

This is how most people should use GAIA — you skip standing up Postgres, Mongo, Redis, ChromaDB and RabbitMQ yourself.

### Self-host — full control

<img src="apps/web/public/images/readme/self-host-installer.webp" alt="The GAIA installer: Node.js, the GAIA CLI and Docker installed, then GAIA downloading with a progress bar and a row per service" width="720" />

Your own server, your own keys and models, your data on your disks.

> [!IMPORTANT]
> The licence is **noncommercial**. Personal and non-profit self-hosting is free; running GAIA inside a business needs an [enterprise licence](https://heygaia.io/contact).

**You need:** a Linux server or Mac with about 8 GB of RAM, and one AI key (OpenAI, OpenRouter, Gemini, or a local Ollama).

**1. Install and start**

```bash
curl -fsSL https://heygaia.io/install.sh | sh
```

It installs the GAIA CLI, then asks to set GAIA up. Say yes: it installs Docker if it's missing, downloads GAIA and starts it on one port.

**2. Open the address it prints** (http://gaia.local on your network, or http://localhost:3000), create your admin account and paste your AI key. That's the whole setup.

<img src="apps/web/public/images/readme/self-host-ready.webp" alt="The end of the install: every step checked, then a card saying GAIA is running, with the gaia.local setup link to open next" width="720" />

**3. Keep it running**

```bash
gaia status   # is everything healthy?
gaia doctor   # what's broken, and how to fix it
gaia update   # upgrade to the latest release
gaia backup   # save your data
```

Want HTTPS on your own domain? `gaia up --domain gaia.example.com`. Every option is in the [walkthrough](https://docs.heygaia.io/self-hosting/walkthrough).

**Prefer a hosting platform?**

<a href="https://render.com/deploy?repo=https://github.com/theexperiencecompany/gaia"><img src="https://render.com/images/deploy-to-render-button.svg" alt="Deploy to Render" height="32" /></a>

Render then needs a few internal addresses filled in, which the [Render guide](https://docs.heygaia.io/self-hosting/one-click-deploy#render) walks through. Coolify (paste one Compose file) and Railway (set up by hand) are in the [deploy options](https://docs.heygaia.io/self-hosting/one-click-deploy), with what each costs and how far each is tested. A plain 8 GB Linux server is the cheapest and the path we test; your ongoing cost there is model API usage plus the server.

Contributing? See [Development Setup](https://docs.heygaia.io/developers/development-setup) for hot-reload local dev.

## Workflows

A few things switch on by themselves the moment you connect a tool:

| What | Turns on with | What it does |
| --- | --- | --- |
| **Inbox desk** | Gmail | Every morning at 8, triages new mail, follows up every thread waiting on you or on someone else, saves reply drafts (never sends), and hands you one briefing |
| **Meeting Briefing** | Calendar | Researches who you're meeting and what it's about, before you walk in |
| **Meeting Reminder** | Calendar | A heads-up 10 minutes out, join link included |

You'll never open a settings screen for those. Build your own from the **Workflows** page:

- **Describe it in plain English** — GAIA writes the steps for you
- **Run it on a schedule** — "every weekday at 9am"
- **Or on an event** — new email, calendar change, Slack message, GitHub commit, Linear issue, Notion edit, new row in a sheet
- **Chain steps across tools** — fetch, summarise, post to Slack

## Examples

Workflows run on their own. This is what you ask it directly.

- **"Summarise my 47 unread emails and draft replies for the 3 that need one."** Reads every thread end to end, ranks by what matters, drafts in your voice.
- **"Turn this call transcript into action items, assign owners and add them to Linear."** Pulls out the decisions, matches them to projects, files the issues.
- **"Watch my email for anything from our investor and ping me on Telegram within 60 seconds."** Persistent background monitoring, cross-channel alert.
- **"When my 2pm gets cancelled, rewrite my todo list to use the freed time."** Watches calendar changes and replans the afternoon against your pending todos.
- **"Draft follow-ups to every email I sent three days ago that nobody answered."** Sweeps your sent mail, writes a personalised nudge per thread.
- **"Research these 10 companies into a table with pricing, team size and funding."** Multi-source research, structured output, ready to paste.
- **"Clean up this CSV, chart the outliers and send me the deck."** Writes real Python, runs it in a real sandbox, hands back a real `.pptx`.
- **"Now run that every Monday at 9am."** Any of the above becomes a standing job, running on a schedule without you.

## Pricing

**$1 a day to never do busywork again.**

| Plan | Cost | What you get |
| --- | --- | --- |
| **Pro** | **$30/month** | Everything GAIA does: chat on iMessage, WhatsApp, Telegram, Slack and Discord, inbox triage and drafted replies every morning, meeting briefs and reminders, todos it works on, workflows that run without you, long-running jobs, memory, priority support |
| **Enterprise** | [Talk to us](https://heygaia.io/contact) | Everything in Pro, plus SSO, SCIM and audit logs, custom integrations, self-host or private cloud, private Slack support, a dedicated engineer and an SLA |

- Pay yearly and two months are free
- **Self-hosting is free** — you cover your own model API costs instead
- Full details on the [pricing page](https://heygaia.io/pricing)

## Platforms

| | Platform | How |
| --- | --- | --- |
| <img src="apps/web/public/images/icons/macos/imessage.webp" width="26" height="26" /> | **iMessage** | [Register your number](https://heygaia.io/settings/linked-accounts), text `/auth`, then just type. [Pro plan](https://heygaia.io/pricing). |
| <img src="apps/web/public/images/icons/macos/whatsapp.webp" width="26" height="26" /> | **WhatsApp** | [Message GAIA](https://wa.me/12762088737) |
| <img src="apps/web/public/images/icons/macos/telegram.webp" width="26" height="26" /> | **Telegram** | [@heygaia_bot](https://t.me/heygaia_bot) — DMs, or `@mention` it in groups |
| <img src="apps/web/public/images/icons/macos/slack.webp" width="26" height="26" /> | **Slack** | [Add to your workspace](https://heygaia.io/slack-bot) |
| <img src="apps/web/public/images/icons/macos/discord.webp" width="26" height="26" /> | **Discord** | [Add the bot](https://heygaia.io/discord-bot) or [join the server](https://discord.heygaia.io) |

- Also on the **web**, a **[desktop app](https://heygaia.io/download)** for macOS, Windows and Linux, and **mobile**
- It's all one account — a chat you start on Telegram shows up in the web app
- Same memory everywhere, no matter where you talk to it

## Integrations

- **One click.** Gmail, Calendar, Slack, Notion, Linear, GitHub, Sheets, Todoist, Trello, HubSpot and more. Each gets its own specialist agent.
- **Anything else, via MCP.** [Model Context Protocol](https://modelcontextprotocol.io) is the open standard for plugging tools into AI models. Point GAIA at any MCP server and its tools work immediately — no fixed catalogue, no waiting on us.
- **A marketplace.** Browse what the community published, or publish your own.
- **Tools on your own computer.** `gaia bridge` links your laptop over one outgoing connection — nothing to forward, no ports to open.

```bash
gaia bridge login          # approve the pairing in your browser
gaia bridge fs ~/projects  # share a folder
gaia bridge up             # connect
```

## Security

GAIA touches your email, your calendar and your files, so we take reports seriously.

Found a vulnerability? Email **security@heygaia.io** — please don't open a public issue. Our full policy is in [SECURITY.md](.github/SECURITY.md).

## FAQ

<details>
<summary><b>What does GAIA store about me, and does it read my email?</b></summary>

Your actual content is never copied into GAIA's database. Email bodies, calendar events and documents are fetched when a request needs them, used, and not kept. GAIA only touches threads relevant to what you asked for, within the scopes you granted on the provider's consent screen.

What *is* stored is under your control:

- **Memory** — everything on the Memory page as a list or graph. Delete items or clear it all. Export as PNG or SVG.
- **Chat history** — one-click clear in Preferences.
- **Workflows, todos, reminders** — managed from their own pages.
- **Integration tokens** — encrypted, and revoked the moment you disconnect from `/integrations`.

</details>

<details>
<summary><b>Can I use my own API keys and models?</b></summary>

**Self-hosted:** yes. Add, replace or remove providers any time in Settings → Providers & Tools (or via environment variables), so you can swap freely.

**Cloud:** no — models are managed for you and usage follows your plan. You can still pick between the available models in the composer.

</details>

<details>
<summary><b>How do I add an integration that isn't in the list?</b></summary>

Add it as an MCP server from `/integrations`. Paste the server URL, connect it privately, and its tools are available right away. You can publish it to the community marketplace if you want to share it.

For tools running on your own machine, use `gaia bridge` instead.

</details>

<details>
<summary><b>What does self-hosting cost?</b></summary>

The code is free under PolyForm Noncommercial, so you pay for model API usage, any paid integrations you opt into, and hosting. See [Self-host](#self-host) above for sizing.

</details>

## Documentation

**[docs.heygaia.io](https://docs.heygaia.io)** — [Quick Start](https://docs.heygaia.io/quick-start) · [Bots](https://docs.heygaia.io/bots/overview) · [Self-Hosting](https://docs.heygaia.io/self-hosting/walkthrough) · [Developers](https://docs.heygaia.io/developers/introduction)

## Repository

Full-stack Nx monorepo.

```
apps
├── web            Next.js web app                    heygaia.io
├── desktop        Electron desktop app (beta)
├── mobile         React Native mobile app (beta)
├── api            FastAPI + LangGraph backend
├── voice-agent    LiveKit voice worker
└── bots           imessage · whatsapp · telegram · slack · discord
packages
└── cli            @heygaia/cli — the gaia command
libs
├── shared/py      gaia-shared
├── shared/ts      shared TypeScript + the unified bot framework
└── wake-word      @gaia/wake-word — on-device "Hey GAIA"
docs               docs.heygaia.io
infra/docker       Docker Compose (development services + self-host)
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

## Contributing

<a href="https://github.com/theexperiencecompany/gaia/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=theexperiencecompany/gaia" />
</a>

Bug fixes, features, docs, tests — all welcome.

> 🤖 **AI and vibe-coded PRs are welcome.** Built it with Claude, Cursor, or anything else? Great — just say so in the PR description.

Start with **[Set up GAIA for development](https://docs.heygaia.io/developers/development-setup)**: it takes you from a fresh clone to a running GAIA, your first change and your first pull request.

[Developer docs](https://docs.heygaia.io/developers/introduction) · [Open a pull request](https://docs.heygaia.io/developers/contributing) · [Code Style](https://docs.heygaia.io/configuration/code-style) · [Commit Messages](https://docs.heygaia.io/configuration/conventional-commits)

Found a bug? [Open an issue](https://github.com/theexperiencecompany/gaia/issues).

## Community

- **[Discord](https://discord.heygaia.io)** — chat with the team and other users
- **[Twitter](https://twitter.com/trygaia)** — news and updates
- **[WhatsApp](https://whatsapp.heygaia.io)** — direct support from our team

## Roadmap

We build in the open. **[View the roadmap](https://gaia.featurebase.app/roadmap)** · **[Request a feature](https://gaia.featurebase.app)**

## License

[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/) — see [LICENSE.md](LICENSE.md).

> [!WARNING]
> This license allows noncommercial use only.

GAIA is built on the shoulders of giants. Full credits at **[heygaia.io/thanks](https://heygaia.io/thanks)**.

---

<div align="center">

If GAIA saves you an hour this week, a ⭐ helps someone else find it.

<br /><br />

Made with ❤️ by [The Experience Company](https://experience.heygaia.io)

[heygaia.io](https://heygaia.io) • [Documentation](https://docs.heygaia.io) • [Contact](https://heygaia.io/contact) • contact@heygaia.io

</div>
