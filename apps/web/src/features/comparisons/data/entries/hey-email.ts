import type { ComparisonData } from "../comparisonsData";

export const entry: ComparisonData = {
  slug: "hey-email",
  name: "HEY Email",
  domain: "hey.com",
  tagline: "A delightfully opinionated take on email",
  description:
    "HEY is an opinionated email service from 37signals that reimagines the inbox with a unique three-section model — the Imbox, The Feed, and Paper Trail. GAIA is a proactive AI productivity OS that manages your email alongside calendar, tasks, workflows, and 50+ integrations — without requiring you to abandon Gmail or adopt a proprietary email address.",
  metaTitle: "HEY Email Alternative with AI Automation | GAIA vs HEY",
  metaDescription:
    "HEY Email reimagines the inbox with an opinionated structure but still requires manual work. GAIA is an open-source HEY Email alternative with AI automation that triages your Gmail, drafts replies, creates tasks, and runs workflows — with a free tier.",
  keywords: [
    "GAIA vs HEY",
    "HEY email alternative",
    "AI email management",
    "HEY email vs AI assistant",
    "inbox zero automation",
    "Gmail AI productivity",
    "proactive AI email assistant",
    "open source HEY alternative",
    "HEY email replacement",
    "email workflow automation",
    "HEY Email free alternative",
    "HEY Email alternative reddit",
    "HEY Email alternative 2026",
    "best HEY Email replacement",
    "HEY Email vs GAIA",
  ],
  intro:
    "HEY Email, built by 37signals, is one of the most opinionated email services ever shipped. Its three-section model — the Imbox for important messages, The Feed for newsletters, and Paper Trail for receipts — is a well-considered philosophy about how email should work. It is a product with genuine conviction. But that conviction comes with significant constraints: HEY requires a @hey.com address or a custom domain through a separate plan, offers no Gmail support, has no third-party API, and has almost no AI beyond basic writing assistance. GAIA approaches email from a fundamentally different angle. Rather than reimagining what an inbox looks like, GAIA deploys AI to manage your existing Gmail inbox proactively — triaging by urgency, drafting context-aware replies, converting emails into tasks, applying labels, and running multi-step workflows across your entire tool stack. HEY asks you to change how you relate to email; GAIA removes most of the work of dealing with it.",
  rows: [
    {
      feature: "Core approach",
      gaia: "Proactive AI productivity OS that manages email, calendar, tasks, and 50+ connected tools autonomously on your behalf",
      competitor:
        "Opinionated email service with a fixed three-section inbox model (Imbox, The Feed, Paper Trail) designed to change how you manually process email",
    },
    {
      feature: "Email management",
      gaia: "Full Gmail automation — reads and triages by urgency, drafts context-aware replies, auto-labels, creates tasks from emails, and drives inbox-zero workflows proactively",
      competitor:
        "Unique screening workflow (Screener) lets you approve new senders before they reach your Imbox; manual sorting into Imbox, The Feed, and Paper Trail with no AI triage",
    },
    {
      feature: "AI features",
      gaia: "Ambient AI that acts without prompting: monitors inbox 24/7, detects urgency, summarizes threads, writes drafts, routes messages to tasks, and executes cross-tool workflows",
      competitor:
        "Very limited AI: basic AI writing assistance added recently; no AI triage, no urgency detection, no autonomous inbox actions — the product is philosophically manual",
    },
    {
      feature: "Task creation from email",
      gaia: "Automatically extracts action items from emails and converts them into structured tasks with priorities, deadlines, and project assignments — no manual intervention required",
      competitor:
        "No native task management and no automatic task creation from email; users must manually forward or copy content to an external task tool",
    },
    {
      feature: "Gmail support",
      gaia: "Native Gmail integration — connects directly to your existing Gmail account via API with full read-write access across your real inbox",
      competitor:
        "No Gmail support whatsoever; requires a @hey.com address on the personal plan or migration to HEY for Domains on the business plan; existing email stays in Gmail",
    },
    {
      feature: "Workflow automation",
      gaia: "Multi-step automations described in natural language with email-triggered actions spanning inbox, calendar, Slack, Notion, GitHub, Linear, and 50+ other tools",
      competitor:
        "No general-purpose workflow automation; no public API, no Zapier support, no CRM integrations — the product explicitly operates as a closed ecosystem",
    },
    {
      feature: "Calendar integration",
      gaia: "Creates and edits Google Calendar events, finds free slots, schedules meetings, generates meeting briefings, and links calendar context back to email and tasks",
      competitor:
        "HEY Calendar is a separate product; it does not integrate with Google Calendar or any third-party calendar service, and supports no external apps",
    },
    {
      feature: "Memory and context",
      gaia: "Graph-based persistent memory that links emails to the tasks they created, the people involved, the meetings where they were discussed, and the projects they belong to",
      competitor:
        "No persistent memory or cross-tool context; contact history is visible per thread, but there is no relational model connecting emails to tasks, projects, or other tools",
    },
    {
      feature: "Integrations",
      gaia: "50+ integrations via MCP including Gmail, Google Calendar, Slack, Notion, GitHub, Linear, Todoist, Asana, ClickUp, and Jira with deep bi-directional actions",
      competitor:
        "No public API, no Zapier support, no third-party integrations; intentionally closed ecosystem — what you see is what you get",
    },
    {
      feature: "Platforms",
      gaia: "Web, desktop (Electron), mobile (React Native), CLI, and bot interfaces for Discord, Slack, and Telegram",
      competitor:
        "Web app, macOS, Windows, Linux desktop apps, iOS, Android, and iPad; no CLI or bot interfaces",
    },
    {
      feature: "Open source",
      gaia: "Fully open source and self-hostable via Docker — your email data never passes through GAIA's servers when self-hosted",
      competitor:
        "Proprietary closed-source SaaS service; no self-hosting option; all data processed through 37signals infrastructure",
    },
    {
      feature: "Pricing",
      gaia: "Free tier available; Pro from $20/month; self-hosting entirely free with no usage caps",
      competitor:
        "HEY for You at $99/year ($8.25/month, annual billing only); HEY for Domains at $12/month per person; no free tier beyond a trial period",
    },
  ],
  gaiaAdvantages: [
    "Works with your existing Gmail account — no email migration, no new address, no disruption to your current workflow or contacts",
    "Proactively manages email without user input — triages urgency, drafts replies, creates tasks, and labels messages before you open your inbox",
    "Connects email to your entire tool stack via 50+ integrations, enabling cross-tool automations that HEY's closed ecosystem cannot support",
    "Graph-based memory links emails, tasks, meetings, and people so every AI action is informed by the full context of your work",
    "Open source and self-hostable — full data sovereignty at no cost, with a hosted Pro plan at a comparable price to HEY's annual plan",
  ],
  competitorAdvantages: [
    "Opinionated Imbox, Feed, and Paper Trail model gives email a clear structure that many users find genuinely reduces cognitive load without any configuration",
    "The Screener workflow eliminates cold email and spam from new senders before they ever reach your inbox — a simple, effective gatekeeping mechanism",
    "Cross-platform native apps for Mac, Windows, Linux, iOS, and Android with a polished, distraction-free design purpose-built around HEY's philosophy",
  ],
  verdict:
    "HEY Email is a thoughtfully opinionated product that solves email overload by imposing structure — the Imbox, The Feed, and Paper Trail give everything a designated place. For users willing to leave Gmail, adopt a new email address, and accept a closed ecosystem with no API or AI, it delivers genuine clarity. GAIA is built for users who do not want to change their email address or client but do want AI to take the burden off them entirely: proactively triaging Gmail, drafting replies, extracting tasks, and automating workflows across their whole tool stack. HEY reorganizes the way you see email; GAIA handles email so you spend less time on it.",
  faqs: [
    {
      question:
        "Can I use GAIA with my existing Gmail account instead of switching to HEY?",
      answer:
        "Yes. GAIA connects directly to your Gmail account via API and works alongside your existing inbox without requiring any migration or new email address. HEY requires you to adopt a @hey.com address on the personal plan or move your domain to HEY for Domains on the business plan, which means giving up your existing Gmail address or maintaining two separate email accounts.",
    },
    {
      question: "Does HEY have AI features comparable to GAIA?",
      answer:
        "HEY has added basic AI writing assistance, but the product is philosophically manual — its value proposition is a better structure for how you personally process email, not AI that acts on your behalf. GAIA's AI runs continuously in the background, detecting urgency, drafting context-aware replies, extracting tasks from email threads, applying labels, and triggering multi-step automations without you initiating any action.",
    },
    {
      question: "Can GAIA integrate with other tools in a way HEY cannot?",
      answer:
        "Yes, significantly. HEY has no public API and explicitly does not support Zapier, CRM integrations, or any third-party tools — it is a closed ecosystem by design. GAIA supports 50+ integrations via MCP including Slack, Notion, GitHub, Linear, Todoist, Asana, ClickUp, and Jira, enabling multi-step email-triggered workflows that span your entire tool stack.",
    },
  ],
};
