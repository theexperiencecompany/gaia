
<div align="center">

# GAIA - Your Personal AI Assistant

<img alt="logo" src="apps/web/public/images/logos/macos.png" width=150 height=150 />

<br />
<br />

[![GAIA](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/theexperiencecompany/gaia/refs/heads/master/apps/web/public/badge.json)](https://heygaia.io) [![Documentation](https://img.shields.io/badge/Documentation-00bbff?style=flat&logo=gitbook&logoColor=white)](https://docs.heygaia.io) 

[![Better Stack Badge](https://uptime.betterstack.com/status-badges/v3/monitor/1zjmp.svg)](https://uptime.betterstack.com/?utm_source=status_badge) ![last update](https://img.shields.io/github/commit-activity/m/theexperiencecompany/gaia) [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/theexperiencecompany/gaia)

[![Discord](https://discord-live-members-count-badge.vercel.app/api/discord-members?guildId=585464664650022914&color=5c6af3&label=Discord)](https://discord.heygaia.io) [![Twitter Follow](https://img.shields.io/twitter/follow/trygaia?style=social)](https://x.com/intent/user?screen_name=trygaia) [![Whatsapp](https://img.shields.io/badge/WhatsApp-25D366?logo=whatsapp&logoColor=fff&style=flat)](https://whatsapp.heygaia.io) 

</div>

![GAIA Demo](apps/web/public/videos/demo.mp4)

**[GAIA](https://heygaia.io)** is your proactive, personal AI assistant designed to increase your productivity.

## Why GAIA?

We all drown in tools. Gmail, Calendar, Todos, Docs, Slack, Linear, WhatsApp — different stacks, same problem. Our days are eaten by small repetitive actions that are not real work. Each task feels small, but together they drain focus and energy. Over time inboxes clog, todo lists rot, and important things slip through.

Most automation doesn't fix this. Tools are rigid, built for power users, and still require you to explain your context every single time. A real personal assistant should already know you — how you write, what you care about, what you ignore. GAIA removes this mental load. One assistant that understands your entire digital life, remembers everything, and proactively handles the boring repetitive work so you can focus on what matters.

---

## Table of Contents

- [Features](#features)
- [Getting Started](#getting-started)
  - [Cloud (zero setup)](#cloud-zero-setup)
  - [Self-host or Develop](#self-host-or-develop)
- [Chat with GAIA on Your Favorite Platforms](#chat-with-gaia-on-your-favorite-platforms)
- [Tech Stack](#tech-stack)
- [Roadmap](#roadmap)
- [Monorepo Structure](#monorepo-structure)
- [Documentation](#documentation)
- [Community & Support](#community--support)
- [Contributing](#contributing)
- [Tools We Love](#tools-we-love)
- [License](#license)
- [Contact](#contact)
- [Star History](#star-history)

---

## Features

- **Truly Proactive AI**: Acts before you ask — deadlines, emails, tasks handled
- **Automated Workflows**: Eliminate repetitive work with multi-step automation
- **Smart Todo Management**: Todos that research, draft, and execute themselves
- **Unified Productivity Hub**: Tasks, email, calendar, and goals — one view
- **Graph-Based Memory**: Everything connected — tasks, projects, meetings, documents
- **Integration Marketplace**: Hundreds of integrations with Gmail, Slack, Notion, and more
- **Multi-Platform**: Web, Desktop (macOS, Windows, Linux), and Mobile
- **Message from anywhere**: Access GAIA on Discord, Slack, Telegram, and WhatsApp
- **Open Source & Self-Hostable**: Full transparency, runs on your own infrastructure

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

Use GAIA directly inside the tools you're already in!

|&emsp;&emsp;&emsp;&emsp; | Platform | How to Use |
|---|---|---|
| <img src="/apps/web/public/images/icons/macos/discord.webp" alt="Discord" width="50" height="50"/>| **Discord** | [Add the bot](https://heygaia.io/discord-bot) or [join the server](https://discord.heygaia.io) — use `/gaia` or `@mention` GAIA in any channel |
| <img src="/apps/web/public/images/icons/macos/slack.webp"  alt="Slack" width="50" height="50" /> | **Slack** | [Add GAIA to your workspace](https://heygaia.io/slack-bot) and use `/gaia` and other slash commands |
|<img src="/apps/web/public/images/icons/macos/telegram.webp" alt="Telegram" width="50" height="50" />|  **Telegram** | [Message @heygaia_bot](https://t.me/heygaia_bot) and send messages or use `/gaia` commands |
|<img src="/apps/web/public/images/icons/macos/whatsapp.webp" alt="WhatsApp" width="50" height="50" />|  **WhatsApp** | [Message GAIA](https://wa.me/12762088737) and send messages or use `/gaia` commands |

See the [Bot Integrations Guide](https://docs.heygaia.io/bots/overview) for setup and usage details.


## Tech Stack

GAIA is a full-stack Nx monorepo spanning web, desktop, mobile, backend, voice, and infrastructure.

| Layer | |
|---|---|
| **Web Frontend** | ![Next.js](https://img.shields.io/badge/Next.js_16-000?style=flat&logo=nextdotjs) ![React](https://img.shields.io/badge/React_19-61DAFB?style=flat&logo=react&logoColor=black) ![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white) ![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=flat&logo=tailwindcss&logoColor=white) ![Zustand](https://img.shields.io/badge/Zustand-443E38?style=flat&logo=react&logoColor=white) ![Framer Motion](https://img.shields.io/badge/Framer_Motion-0055FF?style=flat&logo=framer&logoColor=white) |
| **Desktop** | ![Electron](https://img.shields.io/badge/Electron-47848F?style=flat&logo=electron&logoColor=white) |
| **Mobile** | ![React Native](https://img.shields.io/badge/React_Native-61DAFB?style=flat&logo=react&logoColor=black) ![Expo](https://img.shields.io/badge/Expo-000020?style=flat&logo=expo&logoColor=white) |
| **Backend** | ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white) ![Python](https://img.shields.io/badge/Python_3.11+-3776AB?style=flat&logo=python&logoColor=white) ![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=flat&logo=pydantic&logoColor=white) ![Uvicorn](https://img.shields.io/badge/Uvicorn-499848?style=flat&logo=gunicorn&logoColor=white) |
| **AI / Agents** | ![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=flat&logo=langchain&logoColor=white) ![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=flat&logo=langchain&logoColor=white) ![Mem0](https://img.shields.io/badge/Mem0-000?style=flat&logoColor=white) |
| **LLM Providers** | ![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white) ![Gemini](https://img.shields.io/badge/Google_Gemini-4285F4?style=flat&logo=google&logoColor=white) ![OpenRouter](https://img.shields.io/badge/OpenRouter-6B21A8?style=flat&logoColor=white) |
| **Databases** | ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white) ![MongoDB](https://img.shields.io/badge/MongoDB-47A248?style=flat&logo=mongodb&logoColor=white) ![Redis](https://img.shields.io/badge/Redis-FF4438?style=flat&logo=redis&logoColor=white) ![ChromaDB](https://img.shields.io/badge/ChromaDB-FF6B00?style=flat&logoColor=white) |
| **Queue & Tasks** | ![RabbitMQ](https://img.shields.io/badge/RabbitMQ-FF6600?style=flat&logo=rabbitmq&logoColor=white) ![ARQ](https://img.shields.io/badge/ARQ-FF4438?style=flat&logo=redis&logoColor=white) |
| **Voice & Real-time** | ![LiveKit](https://img.shields.io/badge/LiveKit-DC2626?style=flat&logoColor=white) ![Deepgram](https://img.shields.io/badge/Deepgram-13EF93?style=flat&logoColor=black) ![ElevenLabs](https://img.shields.io/badge/ElevenLabs-000?style=flat&logoColor=white) |
| **Monitoring** | ![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?style=flat&logo=prometheus&logoColor=white) ![Grafana](https://img.shields.io/badge/Grafana-F46800?style=flat&logo=grafana&logoColor=white) ![Sentry](https://img.shields.io/badge/Sentry-362D59?style=flat&logo=sentry&logoColor=white) ![PostHog](https://img.shields.io/badge/PostHog-F54E00?style=flat&logo=posthog&logoColor=white) ![Opik](https://img.shields.io/badge/Opik-6D28D9?style=flat&logoColor=white) |
| **Infrastructure** | ![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white) ![Vercel](https://img.shields.io/badge/Vercel-000?style=flat&logo=vercel&logoColor=white) ![Cloudflare Workers](https://img.shields.io/badge/Cloudflare_Workers-F38020?style=flat&logo=cloudflare&logoColor=white) ![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=flat&logo=githubactions&logoColor=white) |
| **Tooling** | ![Nx](https://img.shields.io/badge/Nx-143055?style=flat&logo=nx&logoColor=white) ![pnpm](https://img.shields.io/badge/pnpm-F69220?style=flat&logo=pnpm&logoColor=white) ![uv](https://img.shields.io/badge/uv-DE5FE9?style=flat&logo=astral&logoColor=white) ![Biome](https://img.shields.io/badge/Biome-60A5FA?style=flat&logo=biome&logoColor=white) ![Ruff](https://img.shields.io/badge/Ruff-D7FF64?style=flat&logo=ruff&logoColor=black) |


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
│   └── shared
│       ├── py           → gaia-shared Python package (used by api, voice-agent, bots)
│       └── ts           → Shared TypeScript utilities
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

## Community & Support

Join our growing community of users and contributors:

- <img src="https://cdn.simpleicons.org/discord/5865F2" alt="Discord" width="16" /> &nbsp;**[Discord](https://discord.heygaia.io)** — Chat with the team and other users.
- <img src="/apps/web/public/images/icons/twitter.webp" alt="Twitter" width="16" /> &nbsp;**[Twitter](https://twitter.com/trygaia)** — Get the latest news and updates.
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

GAIA is built on the shoulders of giants.

We rely heavily on open-source software and world-class developer tools. This page exists to credit the projects that make building GAIA possible and to support the open-source culture that drives real progress.

https://heygaia.io/thanks

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
