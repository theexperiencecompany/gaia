
<div align="center">

# GAIA — Your Personal AI Assistant

[![GAIA](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/theexperiencecompany/gaia/refs/heads/master/apps/web/public/badge.json)](https://heygaia.io) [![Documentation](https://img.shields.io/badge/Documentation-00bbff?style=flat&logo=gitbook&logoColor=white)](https://docs.heygaia.io) [![Better Stack Badge](https://uptime.betterstack.com/status-badges/v3/monitor/1zjmp.svg)](https://uptime.betterstack.com/?utm_source=status_badge) ![last update](https://img.shields.io/github/commit-activity/m/theexperiencecompany/gaia) [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/theexperiencecompany/gaia)

[![Discord](https://discord-live-members-count-badge.vercel.app/api/discord-members?guildId=585464664650022914&color=5c6af3&label=Discord)](https://discord.heygaia.io) [![Twitter Follow](https://img.shields.io/twitter/follow/trygaia?style=social)](https://x.com/intent/user?screen_name=trygaia) [![Whatsapp](https://img.shields.io/badge/WhatsApp-25D366?logo=whatsapp&logoColor=fff&style=flat)](https://whatsapp.heygaia.io)

<br />

https://github.com/user-attachments/assets/19928409-9f05-413f-9ada-d501bc99bc67

</div>

**[GAIA](https://heygaia.io)** is the personal AI assistant that does the work you shouldn't be doing manually — email triage, meeting prep, cross-tool workflows, and everything that quietly eats your day.

<div align="center">

<a href="https://heygaia.io">
<img src="apps/web/public/images/readme/cta-try-gaia-free.png" alt="Try GAIA Free" height="48" />
</a>

<a href="https://docs.heygaia.io/self-hosting/overview">
<img src="apps/web/public/images/readme/cta-self-host.png" alt="Self-host" height="48" />
</a>

</div>

## Why GAIA?

We all drown in tools. Gmail, Calendar, Todos, Docs, Slack, Linear, WhatsApp — different stacks, same problem. Our days are eaten by small repetitive actions that are not real work. Each task feels small, but together they drain focus and energy. Over time inboxes clog, todo lists rot, and important things slip through.

Most automation doesn't fix this. Tools are rigid, built for power users, and ask you to explain your context every single time. A real personal assistant should already know you — how you write, who you work with, what you ignore. GAIA is that assistant. It remembers context across your tools, acts before you ask, and runs the repetitive work in the background while you do the real work.

---

## Table of Contents

- [Features](#features)
- [What you actually ask GAIA](#what-you-actually-ask-gaia)
- [Getting Started](#getting-started)
  - [Cloud (zero setup)](#cloud-zero-setup)
  - [Self-host or Develop](#self-host-or-develop)
- [Chat with GAIA on Your Favorite Platforms](#chat-with-gaia-on-your-favorite-platforms)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Roadmap](#roadmap)
- [Monorepo Structure](#monorepo-structure)
- [Documentation](#documentation)
- [FAQ](#faq)
- [Community & Support](#community--support)
- [Contributing](#contributing)
- [Tools We Love](#tools-we-love)
- [License](#license)
- [Contact](#contact)
- [Star History](#star-history)

---

## Features

An assistant, not a chatbot. The difference shows up in what each of these actually does.

- **Proactive** — Acts before you ask: handles deadlines, drafts replies, flags what matters, and watches events in the background
- **Workflows** — Multi-step automations across your tools, triggered on a schedule or by an event (new email, calendar change, webhook)
- **Smart todos** — Todos that research, draft, and execute themselves, not just reminders
- **Cross-tool memory** — Remembers the people, projects, and preferences that come up across conversations; ask once, it sticks
- **One view** — Tasks, email, calendar, and goals in one place, instead of five browser tabs
- **Integration catalogue** — Gmail, Calendar, Slack, Linear, Notion, and more — plus a community marketplace and custom MCP servers
- **Runs everywhere** — Web, Desktop (macOS, Windows, Linux), Mobile
- **Chat from anywhere** — Ping GAIA on Discord, Slack, Telegram, or WhatsApp — it arrives with your full context
- **Open source & self-hostable** — Full transparency, runs on your own infrastructure

<br />

<div align="center">
  <table>
    <tr>
      <td align="center" width="50%">
        <img src="apps/web/public/images/screenshots/dashboard.png" alt="Dashboard" />
        <br /><sub><b>Dashboard</b></sub>
      </td>
      <td align="center" width="50%">
        <img src="apps/web/public/images/screenshots/todos.png" alt="Smart Todos" />
        <br /><sub><b>Smart Todos</b></sub>
      </td>
    </tr>
    <tr>
      <td align="center" width="50%">
        <img src="apps/web/public/images/screenshots/calendar.png" alt="Calendar" />
        <br /><sub><b>Calendar</b></sub>
      </td>
      <td align="center" width="50%">
        <img src="apps/web/public/images/screenshots/workflows.png" alt="Automated Workflows" />
        <br /><sub><b>Automated Workflows</b></sub>
      </td>
    </tr>
    <tr>
      <td align="center" width="50%">
        <img src="apps/web/public/images/screenshots/desktop_dock.png" alt="Desktop App" />
        <br /><sub><b>Desktop App</b></sub>
      </td>
      <td align="center" width="50%">
        <img src="apps/web/public/images/screenshots/phone_dock.png" alt="Mobile App" />
        <br /><sub><b>Mobile App</b></sub>
      </td>
    </tr>
  </table>
</div>

## What you actually ask GAIA

Real things people use GAIA for — not hypothetical features. Every example below works today.

- **"Summarize the 47 unread emails in my inbox and draft replies for the 3 that actually need one."** GAIA ranks by importance, reads threads end-to-end, and writes drafts in your voice.
- **"Pull my GitHub, Linear, and Slack activity from this week and post a Friday digest to #eng-updates."** Merged PRs, closed issues, channel highlights — gathered, formatted, posted.
- **"When my 2pm gets cancelled, rewrite my todo list to use the freed time."** GAIA watches calendar changes and replans the afternoon against your pending todos and goals.
- **"Before my 1:1 with Alex tomorrow, brief me on everything we've shipped this sprint."** Pulls related PRs, Linear issues, and Slack threads into a single prep doc.
- **"Turn this meeting transcript into action items, assign owners, and add them to Linear."** Extracts decisions, matches them to projects, creates issues with the right assignees.
- **"Watch my email for anything from [investor] and ping me on Telegram within 60 seconds."** Persistent background monitoring, cross-channel notification.
- **"Draft follow-ups to every email I sent more than 3 days ago that hasn't been replied to."** Inbox sweep plus a personalised follow-up draft per thread.
- **"Research these 10 companies and extract their pricing, team size, and funding round into a table."** Web research, structured output, pasted straight into Notion or Sheets.
- **"Every Monday at 9am, scan my calendar and prep a briefing for each meeting."** Scheduled workflow, per-meeting context assembly, waiting for you when you sit down.

## Getting Started

### Cloud (zero setup)

<a href="https://heygaia.io">
  <img src="apps/web/public/images/screenshots/website_tab.png" alt="GAIA Web App" style="width:500px; border-radius:12px;">
</a>

Visit **[heygaia.io](https://heygaia.io)** to get started instantly — no installation required.

### Self-host or Develop

<a href="https://heygaia.io/install">
  <img src="apps/web/public/images/screenshots/cli.png" alt="GAIA CLI" style="width:500px; border-radius:12px;">
</a>

**Prerequisites:** [Node.js](https://nodejs.org) 20+, one package manager (npm/pnpm/bun), [Docker](https://docs.docker.com/get-docker/)

Start with the CLI — it handles setup for both self-hosters and local dev:

```bash
npm install -g @heygaia/cli
# or
pnpm add -g @heygaia/cli
# or
bun add -g @heygaia/cli
gaia init
```

`gaia init` will ask whether you want a **production deployment** or a **local dev environment** and configure everything accordingly.

- Self-hosters → [Self-Hosting Guide](https://docs.heygaia.io/self-hosting/overview)
- Contributors → [Developer Setup](https://docs.heygaia.io/developers/development-setup)


## Chat with GAIA on Your Favorite Platforms

Use GAIA directly inside the tools you're already in.

|&emsp;&emsp;&emsp;&emsp; | Platform | How to Use |
|---|---|---|
| <img src="apps/web/public/images/icons/macos/discord.webp" alt="Discord" width="50" height="50"/>| **Discord** | [Add the bot](https://heygaia.io/discord-bot) or [join the server](https://discord.heygaia.io) — use `/gaia` or `@mention` GAIA in any channel |
| <img src="apps/web/public/images/icons/macos/slack.webp"  alt="Slack" width="50" height="50" /> | **Slack** | [Add GAIA to your workspace](https://heygaia.io/slack-bot) and use `/gaia` and other slash commands |
|<img src="apps/web/public/images/icons/macos/telegram.webp" alt="Telegram" width="50" height="50" />|  **Telegram** | [Message @heygaia_bot](https://t.me/heygaia_bot) and send messages or use `/gaia` commands |
|<img src="apps/web/public/images/icons/macos/whatsapp.webp" alt="WhatsApp" width="50" height="50" />|  **WhatsApp** | [Message GAIA](https://wa.me/12762088737) and send messages or use `/gaia` commands |

See the [Bot Integrations Guide](https://docs.heygaia.io/bots/overview) for setup and usage details.


## Tech Stack

GAIA is a full-stack Nx monorepo spanning web, desktop, mobile, backend, voice, and infrastructure.

| Layer | |
|---|---|
| **Web Frontend** | ![Next.js](https://img.shields.io/badge/Next.js_16-000000?style=flat&logo=nextdotjs&logoColor=white) ![React](https://img.shields.io/badge/React_19-61DAFB?style=flat&logo=react&logoColor=black) ![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white) ![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=flat&logo=tailwindcss&logoColor=white) ![Zustand](https://img.shields.io/badge/Zustand-433E38?style=flat&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAACXBIWXMAAAAAAAAAAQCEeRdzAAAC70lEQVR4nI2Ty08TURTGZ6Yd+qAtbZAAklIstIDtSNsZ2umUTjsdpkChgArlJY+AyENFNBoiChsXJibGnX+BK12buDEkJhpXuNDErRpXrtSVicLnnSEkNLLwJif3ZObc3/3O41LUfy6aptnaupp5d5Wz59iAKpejo76uZoa49sNvDE2baPrA5wJNz7anBtGdiPwksPqywxUs6+nX5C/D3Sn4fQ3Pmxobboo89yIr8e/j0dBui9/3ckwW8HZrCSsF+TfFmIJlAIejMjdTyOD11vLe1aEccrIIAkRB7UKvkiImIZ3kMaokIHGBd3pGZQAzy0bm++S9V5sL+/O9Xch2JZDPJpHPJI19pJgnpiGT6kTzqcZPJhPjLQM4HZXD+RS/N6klkemKG7dqGRHFfAbXFiexsTiOWwujWCgVIQkd4NpbdiSuddZps/qMWnWEgrtaVoKSFpGVOhHj2qEQ0PL0OazPjeLxhIQ74xo2VmcxRpQsFLP4+GgTSjiwTQpojslizJCrEoBC5KdFHioBXJk5j7XZUVwsDWB8UENO4rE0OYy8GMFaQf5Q7bAHKWelrZQjwSopXEFJ4uHKGOYKsgG5NDGEcKuf5O1FQ30NxFgIl4mqOM/B7al6cNABu3VEB+jyS1oKT9cv7F8fVpEguU4M5TE3qOKG4MPSRBG3V2cw0qdAiIZQU+25awBMDBNOxSN/8qQG3ekEBrMi2Yki4ic7I5gaUHGvV8Da9FmU+lXEzrQbAIfdkvXYWIqyWRgqFPTt6EXU9DqQVIwWEssRkBANI07UkMECHwkhGY8g6Dv5JlxtodwWE5kBE03ZrawoREK/VDmBbh1AQDqshwzQAShhWCYlgGvz//C7rdEmF0tG/cgsuF32Enc68D0jCUYLddMVHPoSubnF3/jVZatQHGz5IB55E+Zgk7f2Cdfe/C3KtZJ829ARCiDY3PjZW1t93+u01B1/8sjSX5/NYj7hdlpjlXZrmjWbeYahXfo/lvk3/i/YWhruUi6sTwAAAABJRU5ErkJggg==&logoColor=white) |
| **Desktop** | ![Electron](https://img.shields.io/badge/Electron-47848F?style=flat&logo=electron&logoColor=white) ![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white) |
| **Mobile** | ![React Native](https://img.shields.io/badge/React_Native-61DAFB?style=flat&logo=react&logoColor=black) ![Expo](https://img.shields.io/badge/Expo-000020?style=flat&logo=expo&logoColor=white) ![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white) |
| **Backend** | ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white) ![Python](https://img.shields.io/badge/Python_3.11+-3776AB?style=flat&logo=python&logoColor=white) ![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=flat&logo=pydantic&logoColor=white) |
| **AI / Agents** | ![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=flat&logo=langchain&logoColor=white) ![LiveKit](https://img.shields.io/badge/LiveKit-FF5C28?style=flat&logo=livekit&logoColor=white) ![Deepgram](https://img.shields.io/badge/Deepgram-101820?style=flat&logo=deepgram&logoColor=13EF93) ![ElevenLabs](https://img.shields.io/badge/ElevenLabs-000000?style=flat&logo=elevenlabs&logoColor=white) ![Composio](https://img.shields.io/badge/Composio-7C3AED?style=flat&logoColor=white) ![E2B](https://img.shields.io/badge/E2B-1A1A1A?style=flat&logoColor=white) ![Tavily](https://img.shields.io/badge/Tavily-0EA5E9?style=flat&logoColor=white) |
| **Databases** | ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white) ![MongoDB](https://img.shields.io/badge/MongoDB-47A248?style=flat&logo=mongodb&logoColor=white) ![Redis](https://img.shields.io/badge/Redis-FF4438?style=flat&logo=redis&logoColor=white) ![ChromaDB](https://img.shields.io/badge/ChromaDB-E879F9?style=flat&logoColor=white) |
| **Queue & Tasks** | ![RabbitMQ](https://img.shields.io/badge/RabbitMQ-FF6600?style=flat&logo=rabbitmq&logoColor=white) ![ARQ](https://img.shields.io/badge/ARQ-FF4438?style=flat&logo=redis&logoColor=white) |
| **Monitoring** | ![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?style=flat&logo=prometheus&logoColor=white) ![Grafana](https://img.shields.io/badge/Grafana-F46800?style=flat&logo=grafana&logoColor=white) ![Sentry](https://img.shields.io/badge/Sentry-362D59?style=flat&logo=sentry&logoColor=white) ![PostHog](https://img.shields.io/badge/PostHog-F54E00?style=flat&logo=posthog&logoColor=white) |
| **Bots** | ![Discord.js](https://img.shields.io/badge/Discord.js-5865F2?style=flat&logo=discord&logoColor=white) ![Slack Bolt](https://img.shields.io/badge/Slack_Bolt-4A154B?style=flat&logo=slack&logoColor=white) ![Grammy](https://img.shields.io/badge/Grammy-26A5E4?style=flat&logo=telegram&logoColor=white) ![Kapso](https://img.shields.io/badge/Kapso-25D366?style=flat&logo=whatsapp&logoColor=white) |
| **Infrastructure** | ![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white) ![Vercel](https://img.shields.io/badge/Vercel-000000?style=flat&logo=vercel&logoColor=white) ![Cloudflare Workers](https://img.shields.io/badge/Cloudflare_Workers-F38020?style=flat&logo=cloudflare&logoColor=white) ![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=flat&logo=githubactions&logoColor=white) |
| **Tooling** | ![Nx](https://img.shields.io/badge/Nx-143055?style=flat&logo=nx&logoColor=white) ![pnpm](https://img.shields.io/badge/pnpm-F69220?style=flat&logo=pnpm&logoColor=white) ![uv](https://img.shields.io/badge/uv-DE5FE9?style=flat&logo=uv&logoColor=white) ![mise](https://img.shields.io/badge/mise-FB5E2A?style=flat&logoColor=white) ![Biome](https://img.shields.io/badge/Biome-60A5FA?style=flat&logo=biome&logoColor=white) ![Ruff](https://img.shields.io/badge/Ruff-D7FF64?style=flat&logo=ruff&logoColor=black) |

## Roadmap

We track upcoming features, planned improvements, and in-progress work publicly.

**[View Roadmap](https://gaia.featurebase.app/roadmap)** · **[Submit a Feature Request](https://gaia.featurebase.app)**


## Monorepo Structure

This repository is a full-stack monorepo managed with [Nx](https://nx.dev).

```
gaia
├── apps
│   ├── web              → Next.js web app                  https://heygaia.io
│   ├── desktop          → Electron desktop app (beta)      https://heygaia.io/download
│   ├── mobile           → React Native mobile app (beta)   
│   ├── api              → FastAPI + LangGraph backend
│   ├── voice-agent      → Voice processing worker
│   └── bots
│       ├── discord      → Discord bot
│       ├── slack        → Slack bot
│       └── telegram     → Telegram bot
├── docs                 → Documentation Website            https://docs.heygaia.io
├── packages
│   ├── cli              → @heygaia/cli setup tool           npm install -g @heygaia/cli
│   └── gaia-ui          → @heygaia/ui (wrapper)             https://ui.heygaia.io
├── libs
│   ├── shared
│   │   ├── py           → gaia-shared Python package (used by api, voice-agent, bots)
│   │   └── ts           → Shared TypeScript utilities
│   └── wake-word        → @gaia/wake-word — cross-platform on-device "Hey GAIA" detection
│       │                  (122 KB ONNX, web + electron + react native, ~80 ms time-to-wake)
│       ├── src/core     → platform-agnostic detector + 3-stage openWakeWord pipeline
│       ├── src/web      → onnxruntime-web + AudioWorklet + React hook
│       ├── src/native   → onnxruntime-react-native + audio capture + RN hook
│       ├── models       → bundled ONNX artifacts (mel + embedding + VAD + classifier)
│       └── training     → Python pipeline: Piper TTS synthesis + LibriSpeech negatives + MPS training
└── infra
    └── docker           → Docker Compose configs (dev + prod)
```

For a deeper look at how the pieces connect, see the [Architecture Overview](https://docs.heygaia.io/developers/introduction) in the docs.

## Documentation

Our comprehensive documentation is available at [docs.heygaia.io](https://docs.heygaia.io):

- **[Quick Start](https://docs.heygaia.io/quick-start)** - Get up and running in minutes
- **[Bot Integrations](https://docs.heygaia.io/bots/overview)** - Use GAIA on Discord, Slack, and Telegram
- **[Self-Hosting](https://docs.heygaia.io/self-hosting/overview)** - Deploy GAIA on your infrastructure
- **[For Developers](https://docs.heygaia.io/developers/introduction)** - Contribute and extend GAIA

## FAQ

<details>
<summary><b>Cloud vs self-hosted — what's different for me as a user?</b></summary>

The interface is identical on both. Cloud is zero-setup at [heygaia.io](https://heygaia.io), free to start, with plan-based usage limits and managed infrastructure. Self-hosting gives you full data control, no usage caps, and the ability to swap models freely — in exchange for running the stack on your own machines and bringing your own API keys.

</details>

<details>
<summary><b>How do I connect a new integration?</b></summary>

Open <code>/integrations</code>. Browse by category (Productivity, Communication, Developer, and more) or search by name. Click **Connect** — for providers like Gmail, Calendar, Slack, Linear or Notion, you'll be redirected to their consent screen to grant the scopes GAIA needs; for API-key providers, a modal pops up where you paste the token. Once connected, the sidebar shows the tools that integration unlocks, and a **Disconnect** button revokes access in one click.

Need something that isn't in the catalogue? You can add your own MCP integration from the same page, connect it privately, or publish it to the community marketplace.

</details>

<details>
<summary><b>Does GAIA read my email?</b></summary>

Only the threads relevant to whatever you've asked it to do, and only with the scopes you granted on the provider's OAuth consent screen when you connected Gmail. Email content isn't mirrored into GAIA's database — it's fetched per request. You can disconnect the integration from <code>/integrations</code> at any time, which revokes access immediately.

</details>

<details>
<summary><b>What data does GAIA store about me, and can I delete it?</b></summary>

Yes, all of it is under your control:

- **Long-term memory** — everything GAIA has learned about you (people, projects, preferences) is visible on the **Memory** settings page as a list or interactive graph. Delete individual memories, or clear everything with one button. You can also export your memory graph as PNG or SVG.
- **Chat history** — the **Preferences** settings page has a one-click "Clear chat history".
- **Workflows, todos, and reminders** — all manageable from their respective pages.
- **Integration tokens** — stored encrypted, revoked immediately when you disconnect.

Integration content (email bodies, calendar events, documents) is not persisted — it's fetched on demand when a request needs it.

</details>

<details>
<summary><b>How does GAIA's "proactive" behaviour actually work?</b></summary>

Head to the <b>Workflows</b> page and build one. Two kinds of triggers today:

- **Scheduled** — cron-style ("every weekday at 9am", "first Monday of the month")
- **Event-driven** — new Gmail message, new calendar event, webhooks from Linear / Slack / GitHub / Todoist / Sheets / Docs

Chain steps across your integrations ("fetch → summarise → post to Slack") and GAIA will run the whole thing in the background, no prompt required. When a run produces something you should see — a drafted email, a new todo, a reminder, a suggested calendar event — it lands in the notifications bell in the header and on the <code>/notifications</code> page, where you can approve, edit or dismiss it.

</details>

<details>
<summary><b>Can I bring my own API keys?</b></summary>

On **self-hosted**, yes — provider keys (model providers, integration services) are configured via environment variables. On **cloud**, no — the platform manages models on your behalf and usage is governed by your plan. You can still pick between the available models from the chat composer; which ones are unlocked depends on your plan.

</details>

<details>
<summary><b>What does self-hosting cost to run?</b></summary>

The GAIA code is free under Polyform Strict (noncommercial use). Real costs are: model API usage (scales with how much you use it), any paid-tier integration services you opt into, and hosting — a single modestly-sized VM handles a small team. See the <a href="https://docs.heygaia.io/self-hosting/overview">self-hosting guide</a> for detailed numbers.

</details>

## Community & Support

Join our growing community of users and contributors:

- <img src="https://cdn.simpleicons.org/discord/5865F2" alt="Discord" width="16" /> &nbsp;**[Discord](https://discord.heygaia.io)** — Chat with the team and other users.
- <img src="apps/web/public/images/icons/twitter.webp" alt="Twitter" width="16" /> &nbsp;**[Twitter](https://twitter.com/trygaia)** — Get the latest news and updates.
- <img src="https://cdn.simpleicons.org/whatsapp/25D366" alt="WhatsApp" width="16" /> &nbsp;**[WhatsApp](https://whatsapp.heygaia.io)** — Get direct support from our team.

## Contributing

<a href="https://github.com/theexperiencecompany/gaia/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=theexperiencecompany/gaia" />
</a>

We welcome contributions of all kinds — bug fixes, features, docs, and tests.

> 🤖 **AI & vibe-coded PRs are welcome!** Built it with Claude, Cursor, or any AI tool? That's great — just mention it in the PR description.

**Where to start:**
- [Contributing Guidelines](https://docs.heygaia.io/developers/contributing) — how we work and what we're looking for
- [Development Setup](https://docs.heygaia.io/developers/development-setup) — get your local environment running
- [Code Style Guide](https://docs.heygaia.io/configuration/code-style) — linting, formatting, and conventions
- [Conventional Commits](https://docs.heygaia.io/configuration/conventional-commits) — commit message format
- [Pull Request Guide](https://docs.heygaia.io/configuration/pull-requests) — how to open a great PR

For bugs and feature requests, [open an issue](https://github.com/theexperiencecompany/gaia/issues).

## Tools We Love

GAIA is built on the shoulders of giants — the language models, frameworks, and open-source projects that make this possible. Full credits at **[heygaia.io/thanks](https://heygaia.io/thanks)**.

## License

This project is licensed under the [Polyform Strict License 1.0.0](https://polyformproject.org/licenses/strict/1.0.0/).

> [!WARNING]
> This license allows noncommercial use only.

See the full license terms at [LICENSE.md](LICENSE.md).

## Contact

Feel free to contact the team at contact@heygaia.io or aryan@heygaia.io for any questions

## Star History

<a href="https://www.star-history.com/#theexperiencecompany/gaia&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=theexperiencecompany/gaia&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=theexperiencecompany/gaia&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=theexperiencecompany/gaia&type=Date" />
 </picture>
</a>

---

  <center>

Made with ❤️ by
[![The Experience Company](https://img.shields.io/badge/The%20Experience%20Company-121212?logo=data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyBpZD0iTGF5ZXJfMSIgZGF0YS1uYW1lPSJMYXllciAxIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyOTE3IDI1OTYuMjIiPgogIDxkZWZzPgogICAgPHN0eWxlPgogICAgICAuY2xzLTEgewogICAgICAgIGZpbGw6ICNmZmY7CiAgICAgIH0KICAgIDwvc3R5bGU+CiAgPC9kZWZzPgogIDxwYXRoIGNsYXNzPSJjbHMtMSIgZD0iTTE2MjIuNDQsMTE0MC44MmMtMTcxLjM2LDExNi43Ny0yMTQuNzcsMTM5Ljc0LTI1MC41MSwxOTEuMTktODguNzgsMTI3Ljc4LTk2LjE4LDI3MS45LTkyLjAxLDM1OS42NiwxLjM5LDI3OC44MS00LjY3LDU1MC4xNi0zLjI4LDgyOC45NiwzNDUuNjYtMTQ0LjQ4LDc3NS40OS0zOTcuMDgsMTExNy41LTgzOS45Myw2OC4xMS04OC4xOSw3NjQuMjktOTc0LjMyLDQzNC43Ni0xNDE0LjE0QzI2OTUuMDIsODcuODYsMjQ3Mi4xNyw5LjcxLDIyNTQuMTMsMS41NCwxMzI2Ljc5LTMzLjIsNDg3Ljc3LDUyNS40NywxNTEuOTUsMTExMi4yM2MtLjY0LDEuMTEtMS41NiwyLjczLTIuNzUsNC44Mi01Ni4zNSw5OS4zOS0yMjAuNzIsMzg5LjM2LTExMy44OSw1NDUuMjIsNTMuOTUsNzguNywxNTYuNzgsOTMuNjQsMTc2LjI5LDk2LjQ3LDExMi4zOCwxNi4zMywyMDUuNDUtMzUuNjEsMzE4LjQzLTEwMC45NywxNDguMjctODUuNzcsMjIyLjYzLTEyOC4yNSwyMjMuNjYtMTI4LjkzLDExMC44LTczLjAzLDI5Mi40NS0xMzYuMzUsNDY5LjU5LTI2OS43LjI5LS4yMi01LjQ1LDMuMjctMTYuMzMsOS43OS0xNi43NiwxMC4wNC0zMDguNjksMTE2LjYzLTM5Mi42OCwxNzUuMDYtMTM4LjQ4LDk2LjM0LTUxMC40LDE2Ny44LTU3NC44NSw0OS4zNC02OS44My0xMjguMzMsMTc5Ljg1LTQ1Ni4xOSwyNTguODQtNTYwLjgyLjgxLTEuMDcsNy42Ny0xMC4wNSwxNC40Ny0xOC44NSwzMDguMDItMzk3Ljg0LDcwNC4zNS01NTAuNjgsNzc1LjgzLTU3Ny4yLDM4NC44Mi0xNDIuNzksOTM4LjgxLTE5Ny4xMiwxMDIwLjExLTIxLjE5LDc0LjQ0LDE2MS4xLTE0Mi41OSw0MjAuNDMtMzIxLjkxLDU1OC42OCIvPgogIDxwYXRoIGNsYXNzPSJjbHMtMSIgZD0iTTcyNS4yNiwxNjEyLjcyYy0xMDUuMiw1NC45NC0xOTUuMTQsODguMDYtMjQ3LjQyLDEwNS42NS0xNzYuMDYsNTkuMjUtMjMxLjc3LDMxLjk2LTIzOC4xNCwxMS4xNS04LjU1LTI3LjkxLDE4NS40MS05Ny45NiwyMDkuOTItMTA3LjUxLDc0LjMyLTI4LjkzLDk5LjQ5LTM2Ljc3LDE2My41Ny02NS4wOCw0NS4zMi0yMC4wMiwxNDIuNC02Ni4xNSwyNDMuNTItMTQ0LjA1LDEwLjk1LTguNDMsMjAuMDctMTUuMzgsMzIuMjItMjUuOTIsNDAuMTEtMzQuNzcsOTAuNzItODEuMzksMTMyLjczLTE1OC4zNCwzNy44My02OS4yOSw0OS45My0xNjUuODMsNTQuMDUtMjUyLjUyLDQuMDktLjk5LDIuNjIsNy40MiwyLjk2LDExLjQ0LDcuMjYsODcuNDksMTQuODQsMjM4LjU2LDk3LjU3LDI0NS42OCw2MS42Miw1LjMxLDExMy4xNi0yNy42OSwxNjguNTQtNTMuNzcsMi4yMS0xLjA0LDcuNi00LjU5LDcuMzIsMS40Ny03Mi4wOCw0OC4wMS0xMjAuMzcsOTQuODEtMTQ5LjQ3LDEyNi40Ni0zOS4zOCw0Mi44Mi01Ny43Myw3My4yNi02OS4wMiw5NS4xOS01Ljk5LDExLjY0LTE2LjM5LDMyLjEtMjQuODIsNjAuMzctMjUuMzIsODQuOTgtMjkuMTIsMjI4LjQyLTI5LjEsMjM0LjkxLDAsMCwwLC4xNi0uMDQuMTctMS41Ni4yOS0yMy43OS0yMjQuNi04My45NC0yNDMuNzMtMTIuMjgtMy45MS0yNy44NS0uNzItMzEuNDkuNzUtMTQuMjEsNS43MS0xMTAuODIsOTAuNzYtMjM4Ljk3LDE1Ny42OFoiLz4KPC9zdmc+)](https://experience.heygaia.io)
  <a href="https://heygaia.io">heygaia.io</a> • <a href="https://docs.heygaia.io">Documentation</a> • <a href="https://heygaia.io/contact">Contact Us</a>
</center>
