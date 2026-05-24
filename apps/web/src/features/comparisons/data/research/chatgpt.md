# ChatGPT — Competitive Research
Last updated: 2026-05-05
Sources:
- https://chatgpt.com/pricing/ (403 — mirrored via third parties)
- https://openai.com/business/chatgpt-pricing/ (403 — mirrored via third parties)
- https://intuitionlabs.ai/articles/chatgpt-plans-comparison
- https://openai.com/index/introducing-chatgpt-go/
- https://openai.com/index/introducing-chatgpt-agent/
- https://openai.com/index/introducing-workspace-agents-in-chatgpt/
- https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt
- https://chatgpt.com/features/agent/
- https://chatgpt.com/features/desktop/
- https://chatgpt.com/download/
- https://help.openai.com/en/articles/8590148-memory-faq
- https://felloai.com/chatgpt-pricing-guide-free-go-plus-pro-alternatives-october-2025/

## Product Overview
ChatGPT is OpenAI's flagship consumer AI assistant, serving 900 million weekly active users as of February 2026. It began as a purely reactive chat interface and has evolved to include Agent Mode (autonomous multi-step task execution), scheduled tasks, memory across sessions, workspace agents for teams, and the Atlas browser (macOS; Windows in beta). Available on web, iOS, Android, macOS, and Windows. The default model as of April 23, 2026 is GPT-5.5.

## Pricing
- Free tier: $0 — GPT-5.3 Instant, 10 messages every 5 hours, basic memory, limited deep research, ads shown (US). No agent mode.
- Go: $8/month — 10x more messages, unlimited GPT-5.3 Instant, file uploads, image creation, ads still shown, no GPT-5.5.
- Plus: $20/month — No ads, GPT-5.5 at high weekly limits, GPT-5.4 Thinking, Deep Research (10 runs/month), Sora, Codex, Agent Mode. First tier with full agent capabilities.
- Pro: $200/month — Unlimited o1/GPT-5.5 Pro access, o1 Pro mode, 5x Plus usage. (A $100/month middle tier launched April 9, 2026 offering GPT-5.5 Pro and 5x Plus usage at half the old Pro price.)
- Business: $25/user/month — Workspace agents, Slack/Google Drive/SharePoint/GitHub integrations, shared workspace, team GPTs, no data training, SOC 2 Type II.
- Enterprise: Custom pricing — All Business features + extended context (128K+), SCIM, custom data residency, 24/7 priority support, ISO 27001 certified.
Source: https://intuitionlabs.ai/articles/chatgpt-plans-comparison, https://felloai.com/chatgpt-pricing-guide-free-go-plus-pro-alternatives-october-2025/

## Key Capabilities

### Acts before you ask (proactive)
Partial — ChatGPT Tasks (launched January 2025, expanded 2026) allows users to set scheduled reminders and recurring tasks. ChatGPT proactively sends push notifications or emails when a scheduled task executes. Workspace Agents (Business/Enterprise, launched April 22, 2026) can run on a schedule and pick up Slack requests as they arrive. However, ChatGPT does not independently monitor your inbox or calendar and initiate contact — the user must set up the trigger. It is scheduled-reactive, not fully proactive.
Source: https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt, https://openai.com/index/introducing-workspace-agents-in-chatgpt/

### Multi-step workflows
Yes (Plus and above) — ChatGPT Agents can reason, research, and take actions across tools in multi-step sequences using its own computer. Workspace Agents (Business/Enterprise) can run complex automations on a schedule or triggered by Slack messages. Scheduled tasks support daily/weekly/monthly recurrence, If/Then logic in plain English, and dynamic content generation (e.g. fetch stock prices at a scheduled time rather than just send a reminder).
Source: https://chatgpt.com/features/agent/, https://openai.com/index/introducing-workspace-agents-in-chatgpt/

### Cross-tool memory
Yes — three-layer memory architecture: (1) Saved Memories (user facts and preferences persisted across all conversations), (2) Chat history referencing (retrieval of relevant past conversations), (3) Active session context window. Free users get lightweight continuity. Pro users get unlimited memory and maximum context. Users can turn off memory or use Temporary Chat mode. Memory uses RAG under the hood. Browser Memory (Atlas, Windows beta) also retains browsing context across sessions.
Source: https://help.openai.com/en/articles/8590148-memory-faq, https://www.datastudios.org/post/chatgpt-atlas-for-windows-release-date-features-agent-mode-and-browser-memory-explained

### Integrations
Count: Core integrations in Business/Enterprise: Slack, Google Drive, SharePoint, GitHub, and more.
Major integrations (Business/Enterprise): Slack, Google Drive, SharePoint, GitHub; SAML/SSO; SCIM provisioning.
Custom MCP / marketplace: No native MCP marketplace as a user-facing feature. GPT Builder allows custom GPT creation with actions (API integrations) on Plus and above. Workspace agents in Business can be deployed in Slack.
Source: https://intuitionlabs.ai/articles/chatgpt-plans-comparison

### Cross-channel chat
Web: yes
Mobile (iOS): yes (official app)
Mobile (Android): yes (official app)
Desktop (Mac): yes (official desktop app; voice mode removed from macOS app January 15, 2026 — accessible via web and other platforms)
Desktop (Windows): yes (official desktop app with full voice)
Desktop (Linux): no official app (third-party wrappers exist)
WhatsApp: no — not found on official sources as of 2026-05-05
Slack: yes (Workspace Agents deploy in Slack — Business/Enterprise only)
Telegram: no — not found on official sources as of 2026-05-05
Discord: no — not found on official sources as of 2026-05-05
Source: https://chatgpt.com/download/, https://chatgpt.com/features/desktop/

### Unified view
No — ChatGPT does not offer a unified view combining tasks, email, calendar, and goals. The Schedules page (chatgpt.com/schedules) shows active scheduled tasks but this is not a full productivity dashboard. Chat-centric interface only.
Source: https://chatgpt.com/schedules — absence of unified view noted as of 2026-05-05

### Smart todos that execute
Yes (Plus and above via Agent Mode) — ChatGPT Agent can browse the web, write and run code, manage files, interact with external services, and complete multi-step research-and-execute tasks autonomously. Users can assign complex tasks (e.g. "research competitors and draft a report") and the agent works through them step by step.
Source: https://chatgpt.com/features/agent/

### Approval flow for agent actions
Yes (via SDK / Agents API) — When a tool invocation is about to execute a consequential action, the OpenAI Agents SDK evaluates approval rules. If approval is required, the run pauses and returns a RunToolApprovalItem in the interruptions array, waiting for explicit human approval, rejection, or redirect. In practice within the consumer ChatGPT interface, the agent confirms with the user before taking high-risk or irreversible actions, but the product UX for approval is less formalized than GAIA's dedicated approval flow.
Source: https://openai.github.io/openai-agents-js/guides/human-in-the-loop/

### Cloud vs local
Cloud-only. All processing happens on OpenAI's infrastructure. No self-hosting option.
Source: https://chatgpt.com/pricing/ — no self-hosting option found as of 2026-05-05

### Open source + self-hostable
No — ChatGPT itself is closed source and cloud-only. OpenAI publishes some open-source tooling (Agents SDK, Whisper, etc.) but ChatGPT the product is not open source or self-hostable.
Source: https://chatgpt.com/ — no open-source product page found as of 2026-05-05

## Where it genuinely beats GAIA
1. **Brand recognition and user base**: 900 million weekly active users, the most widely used AI assistant on the planet. Network effects, brand trust, and ubiquity that no competitor has matched.
2. **Model capability**: GPT-5.5 with o1 Pro mode, Deep Research (10 runs/month on Plus), and Codex give it state-of-the-art performance on complex reasoning, coding, and research tasks.
3. **Business/team collaboration**: Workspace Agents with Slack deployment, shared GPT libraries, team workspaces, and enterprise security (SOC 2, ISO 27001, SCIM) make it the strongest option for large-team rollouts.
Source: https://intuitionlabs.ai/articles/chatgpt-plans-comparison, https://openai.com/index/introducing-workspace-agents-in-chatgpt/

## Summary for comparison grid
- 6 pricing tiers from $0 (Free) to custom (Enterprise); Plus at $20/month includes Agent Mode
- Available on web, iOS, Android, macOS, Windows (no Linux desktop, no WhatsApp/Telegram/Discord)
- Scheduled tasks and Workspace Agents enable proactive execution, but user must set up the trigger
- Three-layer cross-session memory included across all tiers (lightweight on free)
- Closed source, cloud-only; no self-hosting; integrations limited to Business/Enterprise tier
