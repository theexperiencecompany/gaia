export type FeatureCategory =
  | "AI Intelligence"
  | "Productivity"
  | "Automation"
  | "Integrations"
  | "Multi-Platform";

export interface FeatureBenefit {
  icon: string;
  title: string;
  description: string;
}

export interface HowItWorksStep {
  number: string;
  title: string;
  description: string;
}

export interface FeatureData {
  slug: string;
  category: FeatureCategory;
  icon: string;
  title: string;
  tagline: string;
  headline: string;
  subheadline: string;
  benefits: [FeatureBenefit, FeatureBenefit, FeatureBenefit];
  howItWorks?: [HowItWorksStep, HowItWorksStep, HowItWorksStep];
  demoComponent: string;
}

export const FEATURE_CATEGORIES: FeatureCategory[] = [
  "AI Intelligence",
  "Productivity",
  "Automation",
  "Integrations",
  "Multi-Platform",
];

export const FEATURES: FeatureData[] = [
  // AI Intelligence
  {
    slug: "smart-chat",
    category: "AI Intelligence",
    icon: "MessageMultiple02Icon",
    title: "Smart Chat",
    tagline: "Conversations that take real action, not just give answers",
    headline: "Ask anything. Watch it happen.",
    subheadline:
      "GAIA understands natural language and takes real action across every tool you've connected — in a single streaming conversation.",
    benefits: [
      {
        icon: "FlashIcon",
        title: "Real actions not just answers",
        description: "Executes tasks, doesn't describe them.",
      },
      {
        icon: "AudioWave01Icon",
        title: "Streaming responses",
        description: "Tool calls, results, and answers appear in real time.",
      },
      {
        icon: "DashboardSquare01Icon",
        title: "Rich interactive output",
        description: "Charts, cards, code blocks, email previews, all inline.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Type your request",
        description: "Ask anything in natural language — no special syntax.",
      },
      {
        number: "02",
        title: "GAIA plans and executes",
        description:
          "Agent selects tools, runs them in sequence, and streams results.",
      },
      {
        number: "03",
        title: "Get a rich interactive result",
        description:
          "Answers render as charts, cards, code blocks, or plain text.",
      },
    ],
    demoComponent: "smart-chat",
  },
  {
    slug: "deep-research",
    category: "AI Intelligence",
    icon: "Search01Icon",
    title: "Deep Research",
    tagline: "Multi-source research synthesized in seconds",
    headline: "Research three angles at once, automatically.",
    subheadline:
      "GAIA decomposes your question, searches in parallel, reads the content, and returns a ranked synthesis with citations — not just a list of links.",
    benefits: [
      {
        icon: "BranchIcon",
        title: "Query decomposition",
        description:
          "Question split into sub-queries for multi-angle coverage.",
      },
      {
        icon: "StarIcon",
        title: "Source ranking",
        description:
          "URLs fetched, read, deduplicated, and ranked by relevance.",
      },
      {
        icon: "LayersIcon",
        title: "Three depth levels",
        description: "Quick (5 sources), Standard (10), Deep (20+).",
      },
    ],
    demoComponent: "deep-research",
  },
  {
    slug: "memory",
    category: "AI Intelligence",
    icon: "BrainIcon",
    title: "Memory",
    tagline: "Builds a knowledge graph of you — remembers everything",
    headline: "Knows your team. Your tools. Your preferences.",
    subheadline:
      "GAIA builds a persistent knowledge graph of who you are, who you work with, and how you prefer to work — updating automatically with every conversation.",
    benefits: [
      {
        icon: "BookmarkAdd01Icon",
        title: "Learns from conversations",
        description:
          "Extracts preferences, entity IDs, and patterns automatically after each exchange.",
      },
      {
        icon: "GitForkIcon",
        title: "Graph relationships",
        description:
          "Memories are linked entities, not a flat list. Visualized and editable.",
      },
      {
        icon: "EyeIcon",
        title: "Full transparency",
        description: "See, edit, or delete every memory GAIA holds about you.",
      },
    ],
    demoComponent: "memory",
  },
  {
    slug: "proactive-ai",
    category: "AI Intelligence",
    icon: "Notification01Icon",
    title: "Proactive AI",
    tagline: "Briefings and actions delivered before you even ask",
    headline: "Your 9am briefing, written before you open your laptop.",
    subheadline:
      "Schedule a morning briefing, set up weekly digests, or trigger alerts — and GAIA delivers them on time, pulling from every tool you've connected.",
    benefits: [
      {
        icon: "Calendar01Icon",
        title: "Scheduled briefings",
        description:
          "Daily/weekly/monthly compiled summaries from inbox, calendar, Slack, GitHub.",
      },
      {
        icon: "ArrowRight01Icon",
        title: "Follow-up suggestions",
        description:
          "After every response, contextual next actions you can execute in one click.",
      },
      {
        icon: "UserSearch01Icon",
        title: "Profile discovery",
        description:
          "During onboarding GAIA crawls your social profiles to instantly understand your context.",
      },
    ],
    demoComponent: "proactive-ai",
  },
  {
    slug: "image-generation",
    category: "AI Intelligence",
    icon: "Image01Icon",
    title: "Image Generation",
    tagline: "Create images from natural language, inline in chat",
    headline: "Describe it. See it in seconds.",
    subheadline:
      "Ask GAIA to create an image and it appears inline in the conversation — no tab switching, no separate tool, no prompting needed.",
    benefits: [
      {
        icon: "MagicWand01Icon",
        title: "Automatic prompt enhancement",
        description:
          "GAIA rewrites your description into a detailed generation prompt before sending.",
      },
      {
        icon: "BubbleChatIcon",
        title: "Inline in chat",
        description:
          "Generated images live inside the conversation alongside text, code, and cards.",
      },
      {
        icon: "PaintBoardIcon",
        title: "Any style",
        description:
          "Photorealistic, illustration, flat design, abstract — describe the style and GAIA matches it.",
      },
    ],
    demoComponent: "image-generation",
  },
  {
    slug: "code-execution",
    category: "AI Intelligence",
    icon: "SourceCodeSquareIcon",
    title: "Code Execution",
    tagline: "Run code in a secure sandbox and see results instantly",
    headline: "Write code. Run it. See the output.",
    subheadline:
      "GAIA executes Python, JavaScript, R, and more in an isolated E2B sandbox — with real output, error messages, and automatic chart detection.",
    benefits: [
      {
        icon: "CodeIcon",
        title: "Six languages",
        description:
          "Python, JavaScript, TypeScript, R, Java, Bash — all supported.",
      },
      {
        icon: "BarChart01Icon",
        title: "Automatic chart rendering",
        description:
          "Matplotlib, Plotly, and other chart outputs are detected and rendered inline.",
      },
      {
        icon: "ShieldIcon",
        title: "Fully isolated",
        description:
          "Code runs in a secure E2B container with no access to your system.",
      },
    ],
    demoComponent: "code-execution",
  },
  {
    slug: "rich-responses",
    category: "AI Intelligence",
    icon: "DashboardBrowsingIcon",
    title: "Rich Responses",
    tagline: "Charts, tables, timelines, and 30+ interactive components inline",
    headline: "AI answers that look like dashboards.",
    subheadline:
      "GAIA generates 36 types of interactive components inline — bar charts, timelines, comparison tables, file trees, status cards, and more — directly in the conversation.",
    benefits: [
      {
        icon: "GridViewIcon",
        title: "36 component types",
        description:
          "Charts, data layouts, content blocks, timelines, code diffs.",
      },
      {
        icon: "DatabaseIcon",
        title: "Data-driven output",
        description:
          "When GAIA queries your data sources, results render as the right component for the data shape.",
      },
      {
        icon: "LayoutIcon",
        title: "No markdown walls",
        description:
          "Complex information presented as structured, interactive UI, not paragraphs.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "GAIA detects the data shape",
        description:
          "Analyzes the structure of the data or response to pick the best format.",
      },
      {
        number: "02",
        title: "Selects the right component",
        description:
          "Chooses from 36 component types based on data characteristics.",
      },
      {
        number: "03",
        title: "Renders it outside the chat bubble",
        description:
          "Interactive component appears inline — you interact directly.",
      },
    ],
    demoComponent: "rich-responses",
  },
  // Productivity
  {
    slug: "todos",
    category: "Productivity",
    icon: "CheckListIcon",
    title: "Tasks & Todos",
    tagline: "Smart task management that understands natural language",
    headline: "Tasks that understand plain English.",
    subheadline:
      'Type "call Alex tomorrow @finance p1" and GAIA creates the task with the right priority, due date, and project — no dropdowns, no forms.',
    benefits: [
      {
        icon: "LanguageCircleIcon",
        title: "Natural language parsing",
        description:
          '@project, #label, p1/p2/p3, "next Monday," "in 5 days" — all parsed automatically.',
      },
      {
        icon: "WorkflowCircleIcon",
        title: "AI workflow generation",
        description:
          "For any task, GAIA can generate a multi-step workflow to complete it and run it with one click.",
      },
      {
        icon: "ListViewIcon",
        title: "Subtasks and bulk ops",
        description:
          "Break tasks into subtasks, reorganize by project, complete or delete many at once.",
      },
    ],
    demoComponent: "todos",
  },
  {
    slug: "calendar",
    category: "Productivity",
    icon: "Calendar02Icon",
    title: "Calendar",
    tagline: "Schedule, reschedule, and prep for meetings with AI",
    headline: "Schedule anything without opening your calendar.",
    subheadline:
      "Create events, find free time, prep for meetings, and set recurring schedules — all through natural language, synced with Google Calendar in real time.",
    benefits: [
      {
        icon: "Time04Icon",
        title: "Find free slots",
        description:
          "GAIA scans your calendar, suggests times, and creates the event in one step.",
      },
      {
        icon: "Calendar03Icon",
        title: "Meeting prep",
        description:
          "Before any call, pull agenda, attendee context, and related emails in seconds.",
      },
      {
        icon: "RepeatIcon",
        title: "Recurring events",
        description:
          '"Every weekday at 9am" becomes a proper recurrence rule automatically.',
      },
    ],
    demoComponent: "calendar",
  },
  {
    slug: "email",
    category: "Productivity",
    icon: "Mail01Icon",
    title: "Email",
    tagline: "Triage, summarize, and compose email through AI",
    headline: "Inbox zero, with AI doing the work.",
    subheadline:
      "GAIA reads your inbox, summarizes threads, drafts replies in your tone, and handles bulk operations — so you spend minutes on email, not hours.",
    benefits: [
      {
        icon: "FilterIcon",
        title: "AI triage",
        description:
          "GAIA scans, flags important emails, and summarizes threads so you know what needs attention.",
      },
      {
        icon: "Edit01Icon",
        title: "Tone-matched drafts",
        description:
          "Tell GAIA what to say; it writes it in your style with length and formality controls.",
      },
      {
        icon: "CheckListIcon",
        title: "Bulk operations",
        description:
          "Mark, archive, star, and delete dozens of emails through a single conversation instruction.",
      },
    ],
    demoComponent: "email",
  },
  {
    slug: "goals",
    category: "Productivity",
    icon: "Target02Icon",
    title: "Goals",
    tagline: "Set a goal — get an AI-generated roadmap to achieve it",
    headline: "Turn ambitions into step-by-step roadmaps.",
    subheadline:
      "Describe a goal in one sentence and GAIA generates a structured roadmap with milestones — then tracks your progress as you complete each step.",
    benefits: [
      {
        icon: "ChartBarLineIcon",
        title: "AI roadmap generation",
        description:
          "From a one-line description, a multi-step plan with specific achievable milestones.",
      },
      {
        icon: "ChartIncreaseIcon",
        title: "Progress tracking",
        description:
          "Check off nodes, GAIA tracks overall completion and keeps the roadmap current.",
      },
      {
        icon: "BookOpenIcon",
        title: "60+ goal templates",
        description:
          "Start from a curated library across career, wellness, finance, and creative categories.",
      },
    ],
    demoComponent: "goals",
  },
  {
    slug: "reminders",
    category: "Productivity",
    icon: "AlarmClockIcon",
    title: "Reminders",
    tagline: "Set recurring or one-time reminders in plain language",
    headline: "Reminders that speak your language.",
    subheadline:
      '"Remind me every Monday at 9am to review my pipeline" — GAIA creates the recurring reminder with your timezone, no configuration needed.',
    benefits: [
      {
        icon: "RepeatIcon",
        title: "Recurring patterns",
        description:
          "Cron-powered recurrence with max occurrence limits and stop-after dates.",
      },
      {
        icon: "GlobalIcon",
        title: "Timezone-aware",
        description:
          "All reminders respect your local timezone, no UTC confusion.",
      },
      {
        icon: "Search01Icon",
        title: "Fully searchable",
        description:
          "Find, update, or cancel any reminder by searching across all scheduled notifications.",
      },
    ],
    demoComponent: "reminders",
  },
  {
    slug: "pins",
    category: "Productivity",
    icon: "Pin02Icon",
    title: "Pins",
    tagline: "Save and bookmark any message for later reference",
    headline: "Never lose an important insight again.",
    subheadline:
      "Pin any message from any conversation to save it permanently — then search and browse all your pins in one place.",
    benefits: [
      {
        icon: "Bookmark01Icon",
        title: "One-click saving",
        description:
          "Pin any AI response, tool result, or message instantly from the conversation.",
      },
      {
        icon: "Search01Icon",
        title: "Searchable collection",
        description:
          "Full-text search across all pinned content to find what you saved.",
      },
      {
        icon: "LinkSquare02Icon",
        title: "Context preserved",
        description:
          "Each pin links back to the original conversation for full context.",
      },
    ],
    demoComponent: "pins",
  },
  {
    slug: "dashboard",
    category: "Productivity",
    icon: "DashboardSquare03Icon",
    title: "Dashboard",
    tagline: "Unified view of todos, emails, calendar, and workflows",
    headline: "Your entire work context in one view.",
    subheadline:
      "The GAIA dashboard shows unread emails, upcoming events, today's todos, active workflows, and recent conversations — all updated in real time.",
    benefits: [
      {
        icon: "GridViewIcon",
        title: "Bento widget layout",
        description:
          "Five information widgets arranged in a responsive grid, each pulling live data.",
      },
      {
        icon: "CursorIcon",
        title: "Quick-action entry",
        description:
          "The composer on the dashboard launches a new chat with full context pre-loaded.",
      },
      {
        icon: "RefreshIcon",
        title: "Real-time sync",
        description:
          "All widgets update automatically as emails arrive, events change, or tasks complete.",
      },
    ],
    demoComponent: "dashboard",
  },
  // Automation
  {
    slug: "workflows",
    category: "Automation",
    icon: "WorkflowSquare10Icon",
    title: "Workflows",
    tagline: "Describe an automation in plain language — GAIA builds it",
    headline: "Describe the automation. GAIA builds it.",
    subheadline:
      "Tell GAIA what you want automated in plain language — it generates the steps, picks the integrations, configures the trigger, and runs it on schedule.",
    benefits: [
      {
        icon: "LanguageCircleIcon",
        title: "Plain language creation",
        description:
          "Write one sentence, get a complete multi-step workflow back.",
      },
      {
        icon: "Zap01Icon",
        title: "11+ trigger types",
        description:
          "Schedule, Gmail, Slack, GitHub, Google Sheets, Linear, Notion, Todoist, Asana, and more.",
      },
      {
        icon: "Clock01Icon",
        title: "Full execution history",
        description:
          "Every run logged with status, duration, summary, and conversation link.",
      },
    ],
    howItWorks: [
      {
        number: "01",
        title: "Describe what to automate",
        description: "Tell GAIA what you want in plain language, one sentence.",
      },
      {
        number: "02",
        title: "GAIA generates steps and selects trigger",
        description:
          "Agent builds the workflow, picks integrations, sets the trigger.",
      },
      {
        number: "03",
        title: "Activate and it runs on schedule",
        description:
          "One click to activate. GAIA runs it automatically from that point on.",
      },
    ],
    demoComponent: "workflows",
  },
  {
    slug: "scheduled-automation",
    category: "Automation",
    icon: "Clock01Icon",
    title: "Scheduled Automation",
    tagline: "Run any task daily, weekly, or on any custom schedule",
    headline: "Set it once. Run it forever.",
    subheadline:
      "Schedule any GAIA workflow to run at any frequency — from every 5 minutes to once a month — with per-workflow timezone support and execution tracking.",
    benefits: [
      {
        icon: "Calendar02Icon",
        title: "Visual cron builder",
        description:
          "Build schedules with a UI picker or write a cron expression directly.",
      },
      {
        icon: "GlobalIcon",
        title: "Per-workflow timezones",
        description:
          "Each workflow has its own timezone so global teams get briefings at the right local time.",
      },
      {
        icon: "Analytics01Icon",
        title: "Execution monitoring",
        description:
          "See every past run: when it fired, duration, success/failure, and what it produced.",
      },
    ],
    demoComponent: "scheduled-automation",
  },
  {
    slug: "event-triggers",
    category: "Automation",
    icon: "FlashIcon",
    title: "Event Triggers",
    tagline: "React instantly when something happens across your tools",
    headline: "When X happens, GAIA handles it.",
    subheadline:
      "Wire workflows to fire the moment a new email arrives, a PR is opened, a Notion page is updated, or any other event across your connected apps.",
    benefits: [
      {
        icon: "Mail01Icon",
        title: "Gmail triggers",
        description:
          "Fire when new email arrives: process, categorize, reply, or create a task.",
      },
      {
        icon: "SourceCodeSquareIcon",
        title: "GitHub and Linear",
        description:
          "Trigger on PRs, issues, commits, or status changes automatically.",
      },
      {
        icon: "MessageMultiple02Icon",
        title: "Slack and Sheets",
        description:
          "React to new messages or row additions for data pipelines and alerts.",
      },
    ],
    demoComponent: "event-triggers",
  },
  {
    slug: "document-generation",
    category: "Automation",
    icon: "FileEditIcon",
    title: "Document Generation",
    tagline: "Generate PDFs, DOCX, and HTML from any conversation",
    headline: "Any conversation becomes a document.",
    subheadline:
      "Ask GAIA to generate a report, spec, or export — it produces a fully formatted PDF, DOCX, or HTML file, ready to download instantly.",
    benefits: [
      {
        icon: "File01Icon",
        title: "Six formats",
        description:
          "PDF, DOCX, ODT, HTML, TXT, or EPUB with font, margin, and paper size options.",
      },
      {
        icon: "ListViewIcon",
        title: "Structured output",
        description:
          "Table of contents, section numbering, and clean formatting generated automatically.",
      },
      {
        icon: "Download01Icon",
        title: "Instant download",
        description:
          "Document uploaded to CDN and linked directly in chat. One click to download or share.",
      },
    ],
    demoComponent: "document-generation",
  },
  {
    slug: "skills",
    category: "Automation",
    icon: "PackageIcon",
    title: "Skills",
    tagline: "Install or create custom skills to extend GAIA's capabilities",
    headline: "Teach GAIA new tricks.",
    subheadline:
      "Install skills from GitHub to give GAIA new workflows, or create custom skills in plain language — extending what GAIA knows how to do without code.",
    benefits: [
      {
        icon: "Github01Icon",
        title: "Install from GitHub",
        description:
          "Any GitHub repo following the Agent Skills standard can be installed with one command.",
      },
      {
        icon: "PencilEdit01Icon",
        title: "Create custom skills",
        description:
          "Describe a workflow in natural language and save it as a reusable skill.",
      },
      {
        icon: "PackageIcon",
        title: "30+ built-in skills",
        description:
          "Pre-installed skills for Slack, Gmail, GitHub, Notion, Calendar, artifacts, and more.",
      },
    ],
    demoComponent: "skills",
  },
  // Integrations
  {
    slug: "integrations",
    category: "Integrations",
    icon: "ConnectIcon",
    title: "50+ Integrations",
    tagline: "Connect Gmail, Slack, GitHub, Notion, and 47 more",
    headline: "All your tools. One assistant.",
    subheadline:
      "GAIA connects to Gmail, Slack, GitHub, Notion, Linear, HubSpot, Google Workspace, and 44+ more — with OAuth in one click, no API keys required.",
    benefits: [
      {
        icon: "LinkSquare02Icon",
        title: "One-click OAuth",
        description:
          "Connect any service with a single auth flow, no manual configuration.",
      },
      {
        icon: "WorkflowSquare10Icon",
        title: "Unified tool access",
        description:
          "Every connected service's actions available to GAIA automatically.",
      },
      {
        icon: "ShieldIcon",
        title: "Secure by design",
        description:
          "OAuth tokens scoped to minimum permissions, stored securely per user.",
      },
    ],
    demoComponent: "integrations",
  },
  {
    slug: "marketplace",
    category: "Integrations",
    icon: "Store01Icon",
    title: "Integration Marketplace",
    tagline: "Discover and install community-built integrations",
    headline: "Thousands of integrations, not just fifty.",
    subheadline:
      "Browse and install community-built integrations from the GAIA marketplace — or publish your own for others to use.",
    benefits: [
      {
        icon: "UserGroupIcon",
        title: "Community integrations",
        description:
          "Browse integrations built and published by other GAIA users.",
      },
      {
        icon: "GitForkIcon",
        title: "Clone and customize",
        description:
          "Install a community integration as-is, or fork and modify it for your setup.",
      },
      {
        icon: "Upload01Icon",
        title: "Publish your own",
        description:
          "Build a custom integration and share it publicly with clone count tracking and creator attribution.",
      },
    ],
    demoComponent: "marketplace",
  },
  {
    slug: "mcp-support",
    category: "Integrations",
    icon: "ServerIcon",
    title: "MCP Support",
    tagline: "Connect any Model Context Protocol server",
    headline: "Connect any AI tool, not just GAIA's list.",
    subheadline:
      "GAIA supports the Model Context Protocol — connect any MCP-compatible server and its tools become immediately available to every GAIA agent.",
    benefits: [
      {
        icon: "ServerIcon",
        title: "Any MCP server",
        description:
          "Point GAIA at any HTTP MCP endpoint and its tools are auto-discovered and indexed.",
      },
      {
        icon: "PasswordValidationIcon",
        title: "Auth-aware",
        description:
          "MCP servers requiring OAuth are handled automatically via spec discovery.",
      },
      {
        icon: "BrainIcon",
        title: "Extends subagents",
        description:
          "MCP tools are available to the main agent and specialized subagents alike.",
      },
    ],
    demoComponent: "mcp-support",
  },
  {
    slug: "custom-integrations",
    category: "Integrations",
    icon: "PlusSignIcon",
    title: "Custom Integrations",
    tagline: "Build, publish, and share your own integrations",
    headline: "Build the integration that doesn't exist yet.",
    subheadline:
      "Create a custom integration with any URL, add a bearer token, publish it to the marketplace — and GAIA's agents use it immediately across all your automations.",
    benefits: [
      {
        icon: "LinkSquare02Icon",
        title: "Any HTTP endpoint",
        description:
          "Point to any REST API or MCP server; tools are discovered automatically.",
      },
      {
        icon: "Upload01Icon",
        title: "Publish to marketplace",
        description:
          "Share your integration with the community with one toggle.",
      },
      {
        icon: "PasswordValidationIcon",
        title: "Bearer token or OAuth",
        description:
          "Both authentication methods supported without writing code.",
      },
    ],
    demoComponent: "custom-integrations",
  },
  {
    slug: "contacts",
    category: "Integrations",
    icon: "UserCircleIcon",
    title: "Contacts",
    tagline: "Unified contact lookup across Gmail, HubSpot, and more",
    headline: "Find anyone, across every tool.",
    subheadline:
      "GAIA searches contacts across Gmail, Google Contacts, and HubSpot CRM in one query — with name, email, phone, and company context returned instantly.",
    benefits: [
      {
        icon: "Search01Icon",
        title: "Cross-service search",
        description:
          "Query across Gmail history, Google Contacts, and HubSpot simultaneously.",
      },
      {
        icon: "UserIcon",
        title: "Rich contact cards",
        description:
          "Name, email, phone, and source badge rendered directly in conversation.",
      },
      {
        icon: "BarChart01Icon",
        title: "CRM context",
        description:
          "For HubSpot contacts, see lead status, deal stage, and recent activity alongside contact info.",
      },
    ],
    demoComponent: "contacts",
  },
  {
    slug: "subagents",
    category: "Integrations",
    icon: "BotIcon",
    title: "Specialized Agents",
    tagline: "37 purpose-built agents — one for every integration",
    headline: "A specialist for every integration.",
    subheadline:
      "GAIA has 37 purpose-built subagents — one for each integration — each with scoped tools, specialized instructions, and deep knowledge of that platform's API.",
    benefits: [
      {
        icon: "RouteIcon",
        title: "Automatic routing",
        description:
          "GAIA detects which integration a task involves and routes to the right specialist agent automatically.",
      },
      {
        icon: "BrainIcon",
        title: "Platform expertise",
        description:
          "Each subagent carries specialized prompts and workflows for its service.",
      },
      {
        icon: "Layers01Icon",
        title: "Parallel execution",
        description:
          "Multiple subagents can run simultaneously for complex multi-platform tasks.",
      },
    ],
    demoComponent: "subagents",
  },
  // Multi-Platform
  {
    slug: "voice",
    category: "Multi-Platform",
    icon: "MicrophoneIcon",
    title: "Voice",
    tagline: "Talk to GAIA hands-free — real-time voice conversations",
    headline: "Say it. GAIA handles the rest.",
    subheadline:
      "Activate voice mode and have a real-time conversation — Deepgram transcribes, GAIA responds with ElevenLabs TTS, and all the same tools are available hands-free.",
    benefits: [
      {
        icon: "Clock01Icon",
        title: "Sub-second STT",
        description:
          "Deepgram delivers near-instant transcription so GAIA hears you as you speak.",
      },
      {
        icon: "VoiceIcon",
        title: "Natural TTS",
        description:
          "ElevenLabs generates expressive, natural speech for every GAIA response.",
      },
      {
        icon: "WorkflowSquare10Icon",
        title: "Full tool access",
        description:
          "Voice mode has all the same capabilities as chat: todos, email, research, calendar, workflows.",
      },
    ],
    demoComponent: "voice",
  },
  {
    slug: "slack-bot",
    category: "Multi-Platform",
    icon: "MessageMultiple02Icon",
    title: "Slack Bot",
    tagline: "Use GAIA directly inside your Slack workspace",
    headline: "@GAIA in Slack, doing real work.",
    subheadline:
      "Mention @GAIA in any channel or DM, run slash commands, or receive automated workflow posts — all from inside the Slack your team already uses.",
    benefits: [
      {
        icon: "AtIcon",
        title: "Mention anywhere",
        description:
          "@GAIA in any channel creates tasks, answers questions, and posts updates.",
      },
      {
        icon: "CommandIcon",
        title: "Slash commands",
        description:
          "/gaia, /todo, /workflow — full GAIA capabilities through native Slack commands.",
      },
      {
        icon: "Notification01Icon",
        title: "Workflow posts",
        description:
          "Automated workflows post results directly to Slack channels: briefings, alerts, reports.",
      },
    ],
    demoComponent: "slack-bot",
  },
  {
    slug: "discord-bot",
    category: "Multi-Platform",
    icon: "GameboyIcon",
    title: "Discord Bot",
    tagline: "Full GAIA capabilities in your Discord server",
    headline: "GAIA lives in your Discord server.",
    subheadline:
      "Use slash commands, mention GAIA in channels, execute workflows, and get streaming AI responses — all inside Discord with rich embeds and context menus.",
    benefits: [
      {
        icon: "LayoutIcon",
        title: "Rich embeds",
        description:
          "Discord's embed format lets GAIA render structured, colored, field-based responses.",
      },
      {
        icon: "CursorIcon",
        title: "Context menus",
        description:
          'Right-click any message to "Summarize with GAIA" or "Add as Todo."',
      },
      {
        icon: "UserGroupIcon",
        title: "Server-wide access",
        description:
          "Every team member can use GAIA in any channel with their own linked account.",
      },
    ],
    demoComponent: "discord-bot",
  },
  {
    slug: "telegram-bot",
    category: "Multi-Platform",
    icon: "AirplaneIcon",
    title: "Telegram Bot",
    tagline: "GAIA in your Telegram — commands, DMs, group chats",
    headline: "GAIA in your Telegram, anywhere in the world.",
    subheadline:
      "Use /gaia, /todo, and /workflow commands in DMs or groups — with native command suggestion menus and automatic ephemeral responses in group chats.",
    benefits: [
      {
        icon: "CommandIcon",
        title: "Native command menus",
        description:
          "Telegram's \"/\" suggestion menu is always in sync with GAIA's full command set.",
      },
      {
        icon: "UserGroupIcon",
        title: "Group-friendly",
        description:
          "In group chats, responses are sent as private DMs to avoid spam.",
      },
      {
        icon: "GlobalIcon",
        title: "Global reach",
        description:
          "Telegram works anywhere with a data connection, no VPN or workspace required.",
      },
    ],
    demoComponent: "telegram-bot",
  },
  {
    slug: "mobile",
    category: "Multi-Platform",
    icon: "SmartPhone01Icon",
    title: "Mobile App",
    tagline: "The full GAIA experience on iOS and Android",
    headline: "The full GAIA experience on mobile.",
    subheadline:
      "Every feature available on web — chat, todos, workflows, integrations, voice — optimized for iOS and Android with native push notifications and offline support.",
    benefits: [
      {
        icon: "Notification01Icon",
        title: "Native push notifications",
        description:
          "Workflow completions, reminders, and alerts delivered as OS-level notifications.",
      },
      {
        icon: "DatabaseIcon",
        title: "Offline support",
        description:
          "Message history cached with IndexedDB so you can browse past conversations without a connection.",
      },
      {
        icon: "TouchInteractionIcon",
        title: "Touch-optimized",
        description:
          "iMessage-style bubbles, long-press bulk select, bottom sheets, haptic feedback — built for thumbs.",
      },
    ],
    demoComponent: "mobile",
  },
];

export function getFeatureBySlug(slug: string): FeatureData | undefined {
  return FEATURES.find((f) => f.slug === slug);
}

export function getFeaturesByCategory(
  category: FeatureCategory,
): FeatureData[] {
  return FEATURES.filter((f) => f.category === category);
}
