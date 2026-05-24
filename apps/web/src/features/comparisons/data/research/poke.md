# Poke — Competitive Research
Last updated: 2026-05-05
Sources:
- https://techcrunch.com/2026/04/08/poke-makes-ai-agents-as-easy-as-sending-a-text/
- https://aitoolinsight.com/poke-ai-agent-text-message/
- https://poke.com/faq
- https://techfundingnews.com/poke-launches-15m-seed-imessage-ai-assistant/
- https://moge.ai/product/poke
- https://x.com/alexkaplan0/status/1965158155002020019
- https://handyai.substack.com/p/getting-free-access-to-pokes-ai-agent
- https://www.webwire.com/ViewPressRel.asp?aId=343533

## Product Overview
Poke (by The Interaction Company) is an AI personal assistant that lives entirely inside iMessage, SMS, and Telegram — no app to download, no account setup beyond a phone number. It launched publicly in March 2026 after raising $25M total ($15M seed from General Catalyst + $10M follow-on) at a $300M post-money valuation. The core concept: make AI agents as approachable as texting a friend. Poke monitors your inbox and calendar, sends proactive nudges, and executes pre-built automations ("recipes") on behalf of the user.

## Pricing
- Free tier: Yes — basic queries that do not require real-time data lookups are free indefinitely.
- Paid tier: No fixed subscription tiers. Pricing is usage-based and negotiated directly with the AI agent. Beta users landed at $10–$30/month depending on usage intensity. Real-time inference features (email triggers, live flight check-ins) incur costs.
- Enterprise: Unknown — not found on official sources as of 2026-05-05.
Source: https://poke.com/faq, https://x.com/alexkaplan0/status/1965158155002020019, https://techcrunch.com/2026/04/08/poke-makes-ai-agents-as-easy-as-sending-a-text/

## Key Capabilities

### Acts before you ask (proactive)
Yes — proactivity is the core proposition. Poke monitors Gmail, Outlook, Google Calendar, and other connected services and initiates conversations with the user when it detects relevant signals: incoming invoices, travel updates, meeting requests, fitness goal check-ins, weather alerts, sports score updates. Users receive one-tap action options within the conversation thread.
Source: https://aitoolinsight.com/poke-ai-agent-text-message/, https://techcrunch.com/2026/04/08/poke-makes-ai-agents-as-easy-as-sending-a-text/

### Multi-step workflows
Yes — via "recipes" (pre-built automations) and user-defined automations in plain English. Recipe categories include: health/wellness, productivity, finance, scheduling, travel, smart home, education, email management, community, and developer tools. Custom recipes can be defined in plain text and shared with others via a creator marketplace. However, complex multi-step cron-style scheduling appears limited compared to GAIA — recipes are mostly trigger-action patterns rather than full multi-step pipelines.
Source: https://aitoolinsight.com/poke-ai-agent-text-message/, https://poke.com/faq

### Cross-tool memory
Unknown — not explicitly documented on official sources as of 2026-05-05. The FAQ notes that user data is not used for model training ("Maximum Privacy" default). No mention of persistent cross-session memory or a memory graph.
Source: https://poke.com/faq — absence noted as of 2026-05-05

### Integrations
Count: ~20+ documented integrations.
Major integrations:
- Productivity: Gmail, Google Calendar, Outlook, Notion, Linear, Granola
- Health/fitness: Strava, Withings, Oura, Fitbit
- Smart home: Philips Hue, Sonos
- Developer tools: PostHog, Webflow, Supabase, Vercel, Devin, Sentry, GitHub, Cursor Cloud Agents
Custom MCP / marketplace: Yes — custom integrations via MCP (Model Context Protocol) are supported. Pre-built integration library is browsable and users can request additions.
Source: https://poke.com/faq, https://aitoolinsight.com/poke-ai-agent-text-message/

### Cross-channel chat
Web: no (no web app; text-message only)
Mobile (iOS): yes (via iMessage and SMS)
Mobile (Android): yes (via SMS and Telegram)
Desktop (Mac): yes (via iMessage on Mac and Telegram desktop)
Desktop (Windows): yes (via Telegram desktop)
Desktop (Linux): yes (via Telegram desktop)
WhatsApp: limited (available in Brazil and EU pending regulatory approval; restricted in most markets by Meta's chatbot policy)
Slack: no — not found on official sources as of 2026-05-05
Telegram: yes
Discord: no — not found on official sources as of 2026-05-05
iMessage: yes (primary platform)
SMS: yes
Source: https://techcrunch.com/2026/04/08/poke-makes-ai-agents-as-easy-as-sending-a-text/, https://aitoolinsight.com/poke-ai-agent-text-message/

### Unified view
No — there is no unified dashboard. All interaction happens within messaging threads. There is no combined view of tasks, email, calendar, and goals.
Source: https://poke.com/faq, https://aitoolinsight.com/poke-ai-agent-text-message/

### Smart todos that execute
Partial — Poke can draft replies, reschedule appointments, pay bills, and trigger automations, but the primary model is nudge-and-confirm within the chat thread rather than autonomous execution of complex todos. No evidence of todos that perform multi-step research and deliver a result.
Source: https://techcrunch.com/2026/04/08/poke-makes-ai-agents-as-easy-as-sending-a-text/

### Approval flow for agent actions
Partial — Poke sends one-tap action prompts in the messaging thread before executing consequential actions (e.g. "Reschedule this meeting?" with a tap to confirm). This is a lightweight conversational approval pattern rather than a formal staged approval flow.
Source: https://techcrunch.com/2026/04/08/poke-makes-ai-agents-as-easy-as-sending-a-text/

### Cloud vs local
Cloud-hosted. No self-hosting option. All processing happens on Poke's infrastructure using multi-provider model routing (Linq technology).
Source: https://aitoolinsight.com/poke-ai-agent-text-message/

### Open source + self-hostable
No — closed source, cloud-only. No self-hosting option documented.
Source: https://poke.com/faq — absence noted as of 2026-05-05

## Where it genuinely beats GAIA
1. **Zero-friction onboarding**: No app download, no account creation, no configuration — just text a phone number. The lowest barrier to entry of any AI assistant on the market.
2. **iMessage-native experience**: First-class iMessage integration means iPhone users interact in the app they already live in. GAIA requires opening a separate app or channel.
3. **Creator economy for recipes**: Users earn $0.10–$1.00 per signup by sharing automations, creating organic distribution and a growing library of community-built workflows.
Source: https://techcrunch.com/2026/04/08/poke-makes-ai-agents-as-easy-as-sending-a-text/, https://aitoolinsight.com/poke-ai-agent-text-message/

## Summary for comparison grid
- No-app AI agent living in iMessage, SMS, Telegram (WhatsApp in select markets)
- Free for non-real-time queries; usage-based pricing negotiated with the agent (~$10–$30/month in beta)
- Proactive monitoring of inbox and calendar with one-tap action nudges
- ~20+ integrations via MCP; recipe marketplace with creator monetization
- No web app, no unified view, no desktop-native app, no formal memory layer, closed source
