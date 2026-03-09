import type { ComparisonData } from "../comparisonsData";

export const entry: ComparisonData = {
  slug: "roam-research",
  name: "Roam Research",
  domain: "roamresearch.com",
  tagline: "A note-taking tool for networked thought",
  description:
    "Roam Research is a networked outliner and personal knowledge management tool built around bidirectional links, block references, and daily notes. GAIA is a proactive AI productivity OS that manages your email, calendar, tasks, and workflows — acting on your behalf before you ask.",
  metaTitle: "Roam Research Alternative with Proactive AI | GAIA vs Roam",
  metaDescription:
    "Roam Research is a powerful networked outliner but stays passive and note-focused. GAIA is an open-source Roam Research alternative with proactive AI that manages your inbox, calendar, tasks, and automations across 50+ integrations — turning knowledge into action.",
  keywords: [
    "GAIA vs Roam Research",
    "Roam Research alternative",
    "networked notes alternative",
    "Roam Research vs AI assistant",
    "PKM with AI automation",
    "Roam Research replacement",
    "bidirectional links productivity app",
    "AI-powered note taking",
    "Roam Research email integration",
    "personal knowledge management AI",
    "networked outliner alternative",
    "proactive AI assistant vs Roam",
  ],
  intro:
    "Roam Research pioneered the networked outliner category and built a devoted following among researchers, writers, and knowledge workers who think in interconnected blocks. Its bidirectional links, block references, and daily notes page create a system where ideas accumulate value over time — every note becomes a node in a growing graph of thought. For building a second brain from your reading, research, and reflection, Roam remains a genuinely powerful tool. But Roam is fundamentally a place to capture and connect what you think — it does not read your inbox, create tasks from emails, manage your calendar, or run automations on your behalf. GAIA operates in an entirely different category. Rather than offering a canvas for your ideas, GAIA actively monitors and manages your digital life: triaging email, preparing meeting briefings, managing your todos, and running multi-step automations across 50+ tools without being prompted. Where Roam helps you build knowledge, GAIA handles execution.",
  rows: [
    {
      feature: "Core approach",
      gaia: "Proactive AI productivity OS that monitors your email, calendar, tasks, and connected tools and acts on your behalf automatically",
      competitor:
        "Networked outliner and PKM tool for capturing, linking, and exploring knowledge through bidirectional block references and a daily-notes-based workflow",
    },
    {
      feature: "Note structure",
      gaia: "Conversational AI interface with structured task, calendar, and workflow management; context and notes are stored in a graph-based memory system connecting tasks, people, and projects",
      competitor:
        "Block-based outliner with bidirectional page and block references, daily notes as the default capture surface, and a visual graph view for navigating accumulated knowledge",
    },
    {
      feature: "Email management",
      gaia: "Full Gmail management — triages inbox by urgency, drafts context-aware replies, auto-labels threads, and creates tasks directly from emails without manual input",
      competitor:
        "No email integration. Emails must be manually copied or summarized into Roam pages; no inbox triage, reply drafting, labeling, or automated email management of any kind",
    },
    {
      feature: "Task management",
      gaia: "AI-powered todos with priorities, projects, deadlines, and automatic task creation from emails, calendar events, and conversations",
      competitor:
        "TODO/DONE block markers and queries enable basic task tracking within the outliner; no AI prioritization, deadline management, or automated task creation from external sources",
    },
    {
      feature: "AI capabilities",
      gaia: "Native proactive AI that creates tasks, drafts emails, schedules meetings, executes automations, and surfaces insights across 50+ tools without being prompted",
      competitor:
        "No built-in AI assistant; community SmartBlocks and third-party extensions can invoke LLMs for text generation within notes, but all AI interactions require manual initiation",
    },
    {
      feature: "Automation",
      gaia: "Natural language multi-step automations with triggers, conditions, and cross-tool actions spanning email, calendar, Slack, Notion, GitHub, and more",
      competitor:
        "SmartBlocks enable template-based automation and date-stamped insertions within the Roam graph; no cross-tool or external service automation engine",
    },
    {
      feature: "Calendar integration",
      gaia: "Creates and edits Google Calendar events, finds available slots, schedules meetings, and auto-generates pre-meeting briefings from email and task context",
      competitor:
        "No native calendar integration; dates and meeting notes can be manually entered on daily notes pages, but no event creation, scheduling, or calendar sync is available",
    },
    {
      feature: "Open source",
      gaia: "Fully open source and self-hostable — deploy on your own infrastructure, own your data entirely, and never have it used for model training",
      competitor:
        "Closed-source proprietary SaaS; your data is stored in Roam's cloud and exportable as Markdown or EDN, but the application cannot be self-hosted or audited",
    },
    {
      feature: "Pricing",
      gaia: "Free tier available; Pro from $20/month; self-hosting is free with no usage caps",
      competitor:
        "Believer plan at $500 one-time or $165/year; standard plan at $15/month; no permanent free tier beyond a short trial period",
    },
  ],
  gaiaAdvantages: [
    "Proactively triages your inbox, prepares meeting briefings, and executes workflows without needing to be prompted — Roam requires you to manually capture everything",
    "Full Gmail automation turns email into an action system: drafting replies, labeling threads, and creating prioritized tasks automatically without any copy-pasting",
    "50+ integrations via MCP connect GAIA to Slack, Notion, GitHub, Linear, and more for genuine cross-tool orchestration that Roam cannot approach",
    "Natural language automations replace manual, repetitive workflows across your entire tool stack — not just templated insertions inside a single graph",
    "Fully open source and self-hostable for complete data sovereignty at no per-seat cost, compared to Roam's $15/month closed SaaS subscription",
  ],
  competitorAdvantages: [
    "Best-in-class networked outliner with block-level bidirectional references that create an emergent knowledge graph as you write — unmatched for research-heavy workflows",
    "Daily notes as the default capture surface removes the friction of deciding where to put information, letting knowledge accumulate organically over time",
    "Highly scriptable through SmartBlocks and the Clojure-based API, giving power users deep programmatic control over their Roam database",
  ],
  verdict:
    "Roam Research is the right tool if building a dense, interconnected knowledge graph from your research, reading, and daily thinking is your primary goal. Its block-reference model is genuinely distinctive and has no exact equivalent. GAIA is the right tool if you want an AI assistant that proactively manages your email, calendar, tasks, and workflows — doing the operational work of running your day rather than storing your thoughts. They solve fundamentally different problems: Roam is where you build knowledge; GAIA is where your work gets done.",
  faqs: [
    {
      question:
        "Can GAIA replace Roam Research for personal knowledge management?",
      answer:
        "GAIA and Roam Research serve meaningfully different purposes. Roam is purpose-built for building a networked knowledge graph through block references and daily notes — it excels at long-form research, literature review, and navigating complex idea structures built up over months. GAIA is built for productivity execution: managing email, calendar, tasks, and workflows proactively. GAIA captures contextual notes through conversation, email, and meetings and stores them in a graph-based memory system, but it is not a dedicated outliner or knowledge base editor. Many users find the two complementary: Roam as the thinking and research layer, GAIA as the action and execution layer.",
    },
    {
      question: "Does Roam Research have any AI or automation features?",
      answer:
        "Roam's automation capabilities are limited to SmartBlocks — a community-built templating system that can insert date-stamped content and trigger predefined text expansions within your graph. Some users extend this with third-party scripts that call LLMs to generate or summarize text in notes, but all interactions are manual and confined to the Roam graph itself. There is no built-in AI assistant, no proactive monitoring of email or calendar, and no cross-tool automation engine. GAIA's AI is native and action-oriented: it executes tasks, labels emails, creates calendar events, and runs multi-step workflows autonomously — not just generating text inside a document.",
    },
    {
      question: "Is Roam Research worth the price compared to GAIA?",
      answer:
        "Roam Research costs $15/month or $165/year on its standard plan, with no permanent free tier. GAIA's hosted Pro plan starts at $20/month and includes a free tier, but GAIA can also be self-hosted for free with full data ownership and no usage caps — an option Roam does not offer. The more important comparison is value delivered: Roam's price buys a networked outliner for knowledge capture, while GAIA's price buys a proactive AI assistant that manages your inbox, calendar, tasks, and cross-tool automations. For users whose bottleneck is execution rather than knowledge capture, GAIA delivers substantially more operational leverage per dollar.",
    },
  ],
};
