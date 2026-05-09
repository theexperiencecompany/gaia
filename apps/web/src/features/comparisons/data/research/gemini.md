# Gemini — Competitive Research
Last updated: 2026-05-05
Sources:
- https://gemini.google/subscriptions/
- https://gemini.google/overview/apps/
- https://9to5google.com/2026/04/27/gemini-proactive-assistance/
- https://workspace.google.com/blog/product-announcements/10-more-announcements-workspace-at-next-2026
- https://workspaceupdates.googleblog.com/2025/05/google-workspace-apps-are-now-generally-available-for-the-gemini-app.html
- https://ai.google.dev/gemini-api/docs/pricing
- https://one.google.com/about/google-ai-plans/
- https://9to5google.com/2026/04/11/google-ai-pro-ultra-features/
- https://costbench.com/software/ai-chatbots/gemini/
- https://github.com/google-gemini/gemini-cli
- https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemini-cli-open-source-ai-agent/
- https://markets.financialcontent.com/wral/article/tokenring-2026-1-13-the-agentic-surge-google-gemini-3-desktop-growth-outpaces-chatgpt-as-gmail-proactive-assistant-redefines-productivity

## Product Overview
Gemini is Google's AI assistant family, covering consumer apps (Gemini app on Android/iOS/web), Workspace integration (Gmail, Docs, Sheets, Slides, Calendar, Meet, Drive), and the developer API. The current flagship model as of May 2026 is Gemini 3.1 Pro (consumer plans) with Gemini 3.1 Flash for lower-cost API access. Gemini's unique strength is deep integration into Google's existing ecosystem — it is already inside every Gmail inbox, Google Doc, and Android phone. "Proactive Assistance" (announced Google I/O 2025, rolling out 2026) is an emerging feature that monitors screen content and notifications to suggest actions without being asked.

## Pricing
- Free tier: $0 — Gemini 3.1 Flash, Deep Research, Gemini Live, Canvas, Gems, basic image/video creation, 100 monthly AI credits, 15 GB storage. Limited Gemini 3.1 Pro access.
- AI Plus: $7.99/month — Gemini 3.1 Pro (higher access), 128K context window in app, expanded NotebookLM, 200 monthly AI credits, 200 GB storage. Available in 160+ countries.
- AI Pro: $19.99/month — Gemini 3.1 Pro at full 1M token context, ~100 Pro prompts/day, 1,000 monthly AI credits, 5 TB storage, Gemini Code Assist, Veo 3.1 video generation, unlimited slide generation, Google Antigravity agent access.
- AI Ultra: $249.99/month — Highest access to all capabilities, Gemini 3.1 Pro + Deep Think, Gemini Agent (US/English only), 25,000 monthly AI credits, 30 TB storage, YouTube Premium included.
- Google Workspace (for business): Gemini bundled into all Workspace plans since January 2025, no separate add-on required.
- Enterprise: Gemini Enterprise app (Google Cloud) with custom pricing and agent governance controls.
Source: https://gemini.google/subscriptions/, https://9to5google.com/2026/04/11/google-ai-pro-ultra-features/, https://costbench.com/software/ai-chatbots/gemini/

## Key Capabilities

### Acts before you ask (proactive)
Yes (in development, rolling out 2026) — "Proactive Assistance" is a named feature in the Gemini app that monitors calendar events, Gmail content, on-screen activity, and device notifications to surface personalized suggestions at the right time — without being asked. Example demonstrated at Google I/O 2025: Gemini detects an upcoming exam in Calendar and proactively sends a notification with a practice quiz it generated. "Daily brief" (formerly "Your Day" feed) is the early live implementation. AI Inbox in Gmail uses Gemini to create a proactive inbox assistant. Data is processed in a private, encrypted on-device space and not used for model training.
Source: https://9to5google.com/2026/04/27/gemini-proactive-assistance/

### Multi-step workflows
Yes (AI Pro and above, Workspace) — Google Workspace Flows (announced Cloud Next 2026) enable agentic automation across Docs, Sheets, Gmail, Calendar, and third-party apps like HubSpot and Salesforce. Workspace Studio allows creating and deploying agentic skills across teams (e.g. invoice review automation). Auto Browse in Chrome supports multi-step task automation across web and apps. Computer Use lets Gemini navigate websites, fill forms, and execute browser workflows autonomously (AI Pro+).
Source: https://workspace.google.com/blog/product-announcements/10-more-announcements-workspace-at-next-2026

### Cross-tool memory
Partial — Gemini can reference user data across connected Google apps (Gmail, Calendar, Drive, Tasks, Keep) within a session when Workspace apps are enabled. NotebookLM provides document-level persistent memory for research. No evidence of a cross-session persistent memory graph equivalent to GAIA's. Memory across conversations in the Gemini app is not explicitly documented as a persistent feature as of 2026-05-05.
Source: https://workspaceupdates.googleblog.com/2025/05/google-workspace-apps-are-now-generally-available-for-the-gemini-app.html — cross-session memory not confirmed as of 2026-05-05

### Integrations
Count: Deep native integration across Google's entire product suite; third-party integrations via Workspace MCP Server (preview, Cloud Next 2026).
Major integrations (native): Gmail, Google Calendar, Google Drive, Google Docs, Google Sheets, Google Slides, Google Meet, Google Maps, Google Keep, Google Tasks, YouTube Music, Chrome, Android OS.
Third-party via Workspace MCP / Flows: HubSpot, Salesforce (Sheets imports); additional third-party integrations via Workspace Studio skills and the new Workspace MCP Server.
Custom MCP / marketplace: Yes — Workspace MCP Server (preview) enables developers to integrate Workspace into external AI applications. Workspace Studio provides a skills/agent deployment platform for teams.
Source: https://gemini.google/overview/apps/, https://workspace.google.com/blog/product-announcements/10-more-announcements-workspace-at-next-2026

### Cross-channel chat
Web: yes (gemini.google.com)
Mobile (iOS): yes (official Gemini app; major redesign rolling out May 2026)
Mobile (Android): yes (official Gemini app; deeply integrated into Android OS)
Desktop (Mac): yes (Gemini for Mac app, web app)
Desktop (Windows): yes (web app; no standalone Windows desktop app confirmed as of 2026-05-05)
Desktop (Linux): yes (web app; Gemini CLI open source terminal agent)
WhatsApp: no — not found on official sources as of 2026-05-05
Slack: no — not found on official sources as of 2026-05-05 (Workspace Chat integration exists but not Slack)
Telegram: no — not found on official sources as of 2026-05-05
Discord: no — not found on official sources as of 2026-05-05
Source: https://gemini.google/overview/apps/, https://github.com/google-gemini/gemini-cli

### Unified view
Partial — Gemini's "unified tools section" groups Images, Videos, Music, Canvas, Deep Research, and Guided Learning in one UI (tested on Android and desktop, live on Gemini for Mac as of May 2026). Google Workspace integration means Gemini can surface and act on tasks, email, and calendar events together within a conversation. However, there is no dedicated unified dashboard combining tasks + email + calendar + goals as a standalone view. The experience is assistant-in-Gmail and assistant-in-Calendar rather than a purpose-built productivity hub.
Source: https://www.business-standard.com/technology/tech-news/google-set-to-redesign-gemini-app-across-android-and-apple-ios-what-s-new-126050401028_1.html

### Smart todos that execute
Partial — Gemini can create calendar events, add tasks, manage reminders, and draft documents. Workspace Flows enable multi-step agentic automation (e.g. invoice review). Computer Use (AI Pro+) enables autonomous browser task execution. However, Gemini does not have a first-class "smart todo" concept where a task item itself triggers research, drafting, and execution. The capabilities exist but are scattered across Workspace tools rather than unified in a todo system.
Source: https://workspace.google.com/blog/product-announcements/10-more-announcements-workspace-at-next-2026

### Approval flow for agent actions
Partial — Workspace agent governance controls (announced Cloud Next 2026) include an AI control center and management tools for monitoring agent data access. Workspace Flows can include policy document review and human flagging steps before approval. Gemini CLI has active approval mode support (recent fix noted in release notes). However, a consumer-facing "approve before acting" flow for individual users is not documented as a standard feature as of 2026-05-05.
Source: https://workspace.google.com/blog/product-announcements/10-more-announcements-workspace-at-next-2026, https://github.com/google-gemini/gemini-cli/releases

### Cloud vs local
Cloud-hosted (Google infrastructure). Proactive Assistance data is processed on-device in a private encrypted space, but the model itself is cloud-based. Gemma 4 models (open-weight, separate from Gemini) can be run locally. The Gemini CLI tool is open source but makes API calls to Google's cloud.
Source: https://9to5google.com/2026/04/27/gemini-proactive-assistance/, https://github.com/google-gemini/gemini-cli

### Open source + self-hostable
Partial — Gemini the product is closed source and cloud-only. However: (1) Gemini CLI is open source (github.com/google-gemini/gemini-cli) — an AI agent for the terminal. (2) Gemma 4 is Google's open-weight model family that can be self-hosted. The consumer Gemini app and API are not self-hostable.
Source: https://github.com/google-gemini/gemini-cli, https://www.analyticsvidhya.com/blog/2026/04/googles-gemma-4-open-source-model/

## Where it genuinely beats GAIA
1. **Native Google ecosystem depth**: Gemini is already inside Gmail, Google Docs, Calendar, Drive, and Android for every Google user with no setup. The install-less reach is unmatched — no other assistant has this embedded distribution advantage.
2. **Proactive Assistance with on-device privacy**: The emerging Proactive Assistance feature monitors screen content and notifications with data processed locally in an encrypted space. The combination of proactivity and on-device processing is a strong privacy positioning.
3. **Enterprise Workspace automation**: Workspace Flows + Workspace Studio + HubSpot/Salesforce integrations give enterprise teams a powerful native automation layer built directly into tools they already use daily, without any additional setup or cost.
Source: https://9to5google.com/2026/04/27/gemini-proactive-assistance/, https://workspace.google.com/blog/product-announcements/10-more-announcements-workspace-at-next-2026

## Summary for comparison grid
- 4 consumer tiers: Free ($0), AI Plus ($7.99), AI Pro ($19.99), AI Ultra ($249.99); Workspace bundled for business
- Available on web, iOS, Android, macOS (app), Linux (CLI); no standalone Windows or WhatsApp/Slack/Telegram/Discord
- Proactive Assistance in development (rolling out 2026); deeply embedded in Gmail and Calendar already
- Native integration across the entire Google ecosystem (Gmail, Drive, Calendar, Docs, Sheets, Meet, Maps, YouTube)
- Closed source consumer product; Gemini CLI and Gemma open-weight models are open source
