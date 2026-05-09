# Claude — Competitive Research
Last updated: 2026-05-05
Sources:
- https://claude.com/pricing
- https://claude.com/download
- https://support.claude.com/en/articles/12138966-release-notes
- https://www.anthropic.com/news/claude-4
- https://aimaker.substack.com/p/anthropic-claude-updates-q1-2026-guide
- https://www.buildfastwithai.com/blogs/claude-ai-complete-guide-2026
- https://intuitionlabs.ai/articles/claude-pricing-plans-api-costs
- https://platform.claude.com/docs/en/about-claude/models/overview
- https://www.lorka.ai/knowledge-hub/claude-ai-pricing-plans
- https://claude.com/contact-sales/claude-for-oss

## Product Overview
Claude is Anthropic's AI assistant, positioned around safety, helpfulness, and long-context reasoning. As of 2026 it has expanded from a chat interface into an agentic platform via Claude Cowork (autonomous multi-step desktop agent, GA April 9, 2026) and Claude Code (the leading agentic coding tool, $2.5B ARR annualized as of 2026). The latest flagship model is Claude Opus 4.7 (April 16, 2026). Claude is available on web, iOS, Android, macOS, and Windows. Linux is not officially supported as a desktop app.

## Pricing
- Free tier: $0 — basic chat, web search, file/image analysis, extended thinking, memory (since March 2, 2026), voice mode (limited).
- Pro: $20/month (or $17/month billed annually) — more usage, Claude Code access, Cowork, unlimited projects.
- Max: $100/month (5x Pro usage) or $200/month (20x Pro usage) — early access to advanced features, priority at high traffic, Cowork for heavy workloads.
- Team: $25/seat/month (standard) or $100–$125/seat/month (premium) — organization-wide skill management, partner-built skills directory, shared workspace.
- Enterprise: $20/seat plus API usage costs — self-serve Enterprise launched February 12, 2026; HIPAA-ready, role-based access controls, admin groups, custom retention policies.
Source: https://claude.com/pricing, https://www.lorka.ai/knowledge-hub/claude-ai-pricing-plans

## Key Capabilities

### Acts before you ask (proactive)
Partial — Claude Cowork (Pro/Max and above) supports scheduled recurring and on-demand tasks. Cowork can monitor and act on connected services (Gmail, Calendar, Google Drive via MCP) but the user must configure what to watch. It does not independently detect signals and initiate contact the way GAIA does. The scheduled task feature is close to proactive but still requires user-defined triggers. No evidence of ambient background monitoring without explicit setup.
Source: https://support.claude.com/en/articles/12138966-release-notes, https://www.buildfastwithai.com/blogs/claude-ai-complete-guide-2026

### Multi-step workflows
Yes (Pro/Max and above via Cowork) — Cowork supports scheduled recurring tasks, parallel multi-step workflows via sub-agents, local file access, MCP integrations, and Computer Use (research preview) which lets Claude navigate applications and execute tasks autonomously. Cowork runs inside an isolated VM on the desktop for security. Multi-step tasks include code writing, file management, calendar coordination, email drafting, and browser navigation.
Source: https://support.claude.com/en/articles/12138966-release-notes

### Cross-tool memory
Yes (all tiers including Free since March 2, 2026) — Memory from chat history is available to all users. Auto memory learns work preferences and accumulates context across sessions without re-explanation. Incognito chat mode opts out. Memory persists across all devices (web, mobile, desktop) for the same account. No evidence of a graph-based cross-tool memory store comparable to GAIA's persistent graph memory.
Source: https://support.claude.com/en/articles/12138966-release-notes

### Integrations
Count: Native connectors include Google Drive, Gmail, Google Calendar, Slack, Microsoft 365 (Excel, PowerPoint, Word, Chrome extension), GitHub. Remote MCP support allows connecting any MCP-compatible tool.
Major integrations: Google Drive, Gmail, Google Calendar, Slack, Microsoft 365, GitHub, Apple Health/Fitness (iOS/Android, Pro/Max, US-only).
Custom MCP / marketplace: Yes — remote MCP connectors allow any MCP-compatible service. Team/Enterprise plans include a partner-built Skills directory with organization-wide management. "Agent Skills" is an open standard so skills work across AI platforms.
Source: https://support.claude.com/en/articles/12138966-release-notes, https://claude.com/pricing

### Cross-channel chat
Web: yes (claude.ai)
Mobile (iOS): yes (official app; Health/fitness data analysis on iOS for Pro/Max US)
Mobile (Android): yes (official app)
Desktop (Mac): yes (official desktop app with Cowork + Code)
Desktop (Windows): yes (official desktop app with Cowork + Code; ARM64 and x64)
Desktop (Linux): no (officially not supported as of claude.com/download, 2026-05-05)
WhatsApp: no — not found on official sources as of 2026-05-05
Slack: yes (Slack connector available for Cowork)
Telegram: no — not found on official sources as of 2026-05-05
Discord: no — not found on official sources as of 2026-05-05
Source: https://claude.com/download

### Unified view
No — Claude does not offer a unified view combining tasks, email, calendar, and goals in one dashboard. Cowork provides a task thread interface on desktop but it is not a full productivity hub. Chat-centric.
Source: https://claude.com/ — absence of unified view noted as of 2026-05-05

### Smart todos that execute
Yes (Pro/Max via Cowork) — Cowork can execute multi-step tasks autonomously: write code, manage files, draft and send emails, interact with calendars, browse the web, and coordinate sub-agents in parallel workstreams. Local VM isolation ensures actions don't leak beyond the defined scope.
Source: https://support.claude.com/en/articles/12138966-release-notes

### Approval flow for agent actions
Yes — Cowork tasks run in an isolated VM and Claude surfaces proposed actions for user review when executing consequential steps. The desktop app must be running for Cowork to complete tasks; mobile can assign tasks but cannot execute them, which creates an implicit review checkpoint. OpenTelemetry monitoring support for Cowork activity (launched 2026) enables audit trails.
Source: https://support.claude.com/en/articles/12138966-release-notes, https://claude.com/download

### Cloud vs local
Cloud-hosted (Anthropic infrastructure). Cowork executes in an isolated VM on the user's desktop for local file access, but model inference is cloud-based. No full self-hosting of the Claude service. API access available (Bedrock, Vertex AI, Foundry).
Source: https://claude.com/ — no self-hosting option as of 2026-05-05

### Open source + self-hostable
No — Claude itself is not open source. Anthropic launched the Claude for Open Source program (late February 2026) giving eligible OSS maintainers 6 months of Claude Max 20x free. Claude Code's source code reportedly leaked but was not officially open-sourced. The Claude API is available but the product is closed source and cloud-only.
Source: https://claude.com/contact-sales/claude-for-oss, https://venturebeat.com/technology/claude-codes-source-code-appears-to-have-leaked-heres-what-we-know/

## Where it genuinely beats GAIA
1. **Best-in-class coding agent**: Claude Code is the leading agentic coding tool at $2.5B ARR, with Opus 4.7 delivering the most capable coding and software engineering performance available. GAIA is a personal assistant, not a specialized dev tool.
2. **1M token context window**: Sonnet 4.6 and Opus 4.7 include a 1M token context window, enabling processing of entire codebases, legal document sets, or book-length content in a single prompt.
3. **Safety and trust reputation**: Anthropic's Constitutional AI approach and public safety research give Claude strong institutional trust, particularly for enterprise and regulated industries.
Source: https://support.claude.com/en/articles/12138966-release-notes, https://www.anthropic.com/news/claude-4

## Summary for comparison grid
- 5 tiers from Free ($0) to Enterprise (custom); Pro at $20/month; Max at $100–$200/month
- Web, iOS, Android, macOS, Windows (no Linux desktop, no WhatsApp/Telegram/Discord)
- Cowork enables scheduled multi-step agentic tasks; memory free for all users since March 2026
- Best-in-class coding capability (Claude Code); 1M token context window
- Closed source, cloud-hosted; no self-hosting; Linux desktop support absent
