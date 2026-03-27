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

export interface FeatureFAQ {
  question: string;
  answer: string;
}

export interface FeatureUseCase {
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
  faqs?: [FeatureFAQ, FeatureFAQ, FeatureFAQ, FeatureFAQ];
  useCases?: [FeatureUseCase, FeatureUseCase, FeatureUseCase];
  relatedSlugs?: [string, string, string];
  demoComponent: string;
}

export const FEATURE_CATEGORIES: FeatureCategory[] = [
  "AI Intelligence",
  "Productivity",
  "Automation",
  "Integrations",
  "Multi-Platform",
];

export const CATEGORY_COLORS: Record<
  FeatureCategory,
  { icon: string; bg: string }
> = {
  "AI Intelligence": { icon: "#a855f7", bg: "rgba(168,85,247,0.12)" },
  Productivity: { icon: "#22c55e", bg: "rgba(34,197,94,0.12)" },
  Automation: { icon: "#f97316", bg: "rgba(249,115,22,0.12)" },
  Integrations: { icon: "#3b82f6", bg: "rgba(59,130,246,0.12)" },
  "Multi-Platform": { icon: "#ec4899", bg: "rgba(236,72,153,0.12)" },
};

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
    faqs: [
      {
        question: "Can GAIA take actions or just answer questions?",
        answer:
          "GAIA takes real actions — sending emails, creating calendar events, running code, managing todos, and more. It does not just describe what to do.",
      },
      {
        question: "Does it remember context from earlier in a conversation?",
        answer:
          "Yes — full conversation history is maintained within a session. GAIA also pulls from long-term memory for preferences and facts learned in past conversations.",
      },
      {
        question: "What happens if GAIA misunderstands a request?",
        answer:
          "Correct it in plain language — 'that's not what I meant' followed by a clarification. GAIA will re-plan and retry. No need to start over.",
      },
      {
        question: "Can I use it without connecting any integrations?",
        answer:
          "Yes. Smart Chat works standalone for research, writing, coding, and reasoning. Integrations unlock email, calendar, and tool actions on top of that.",
      },
    ],
    useCases: [
      {
        title: "Drafting and sending email in one step",
        description:
          'Tell GAIA "Reply to the last email from Marcus and say I\'ll have the report by Friday." It drafts, shows a preview, and sends on confirmation.',
      },
      {
        title: "Research synthesis for a meeting",
        description:
          "Ask GAIA to pull the last three months of Slack messages about a project and summarize the key decisions — delivered as a structured timeline card.",
      },
      {
        title: "Multi-step task from a single prompt",
        description:
          'Say "Create a task, block 2 hours on my calendar Friday, and remind me Thursday afternoon." All three actions fire from one message.',
      },
    ],
    relatedSlugs: ["deep-research", "memory", "rich-responses"],
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
    howItWorks: [
      {
        number: "01",
        title: "Submit a question or topic",
        description:
          "GAIA breaks the question into sub-queries covering multiple angles automatically.",
      },
      {
        number: "02",
        title: "Searches and reads sources in parallel",
        description:
          "Multiple searches run simultaneously, pages are fetched and read, duplicates removed.",
      },
      {
        number: "03",
        title: "Returns a ranked synthesis with citations",
        description:
          "Sources are scored by relevance, findings consolidated, and a cited summary delivered.",
      },
    ],
    faqs: [
      {
        question: "How many sources does it actually read?",
        answer:
          "Quick mode reads 5 sources, Standard reads 10, and Deep reads 20 or more. Each source is fully fetched and parsed, not just previewed.",
      },
      {
        question: "Does it search the open web or just a fixed index?",
        answer:
          "It searches the live web — Google, Bing, and direct URL fetching. Results reflect current content, not a static snapshot.",
      },
      {
        question:
          "Can I ask it to focus on specific domains or exclude others?",
        answer:
          "Yes — include instructions like 'only use academic sources' or 'exclude Reddit' and GAIA applies those constraints to its search queries.",
      },
      {
        question: "Are citations included in the output?",
        answer:
          "Yes. Every factual claim is linked to the source page. Citations appear inline in the response and in a collapsible sources panel.",
      },
    ],
    useCases: [
      {
        title: "Competitor landscape in under two minutes",
        description:
          "Ask GAIA to research three competitors' pricing, positioning, and recent news. It returns a comparison table with citations from their websites and press coverage.",
      },
      {
        title: "Technical due diligence on a new library",
        description:
          "Before adopting a new npm package, ask GAIA to research known issues, bundle size, maintenance status, and community sentiment — all in one report.",
      },
      {
        title: "Pre-call research on a prospect",
        description:
          "Paste a LinkedIn URL and ask for a briefing. GAIA returns company size, recent news, funding, and talking points in under 30 seconds.",
      },
    ],
    relatedSlugs: ["smart-chat", "rich-responses", "document-generation"],
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
    howItWorks: [
      {
        number: "01",
        title: "GAIA listens during every conversation",
        description:
          "After each exchange, the agent extracts facts, preferences, and entity relationships from the dialogue.",
      },
      {
        number: "02",
        title: "Facts are stored as linked graph nodes",
        description:
          "Each memory is a typed node connected to related people, projects, and preferences — not a flat list.",
      },
      {
        number: "03",
        title: "Recalled automatically in future conversations",
        description:
          "Relevant memories are retrieved and injected as context before GAIA responds.",
      },
    ],
    faqs: [
      {
        question: "Can I edit or delete a memory GAIA created?",
        answer:
          "Yes. Every memory is visible in the Memory panel. Click any entry to edit the text, change the type, or delete it entirely.",
      },
      {
        question: "Does GAIA remember across different devices?",
        answer:
          "Yes. Memories are stored server-side and sync across web, desktop, mobile, and bot interfaces.",
      },
      {
        question: "How does GAIA decide what to remember?",
        answer:
          "The agent identifies facts about preferences, people, recurring tools, projects, and behavioral patterns. Ephemeral details like 'I'm tired today' are not stored.",
      },
      {
        question: "Is there a limit to how many memories GAIA can hold?",
        answer:
          "There is no hard limit. The graph scales with usage. Memories are semantically indexed so retrieval stays fast regardless of volume.",
      },
    ],
    useCases: [
      {
        title: "Tone preference applied across all drafts",
        description:
          "Tell GAIA once that you prefer short, direct emails. Every draft from that point matches your style without re-stating it.",
      },
      {
        title: "Team context without re-explaining",
        description:
          "After one conversation about your team structure, GAIA knows who owns what. Ask 'who handles billing?' and it answers from memory.",
      },
      {
        title: "Project context carried between sessions",
        description:
          "Start a new chat about a project GAIA has seen before. It recalls the tech stack, open decisions, and last status without you re-explaining.",
      },
    ],
    relatedSlugs: ["smart-chat", "proactive-ai", "contacts"],
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
    howItWorks: [
      {
        number: "01",
        title: "Configure your briefing schedule",
        description:
          "Set a time, frequency, and which sources to pull from — inbox, calendar, Slack, GitHub, or all of them.",
      },
      {
        number: "02",
        title: "GAIA compiles the briefing automatically",
        description:
          "At the scheduled time, the agent queries every connected source and synthesizes the results.",
      },
      {
        number: "03",
        title: "Delivered as a structured summary",
        description:
          "Briefing arrives in chat with sections for urgent emails, today's events, overdue tasks, and suggested actions.",
      },
    ],
    faqs: [
      {
        question: "Can I customize what goes into my morning briefing?",
        answer:
          "Yes. Choose which sources to include (inbox, calendar, Slack, GitHub) and set filters like 'only emails marked urgent' or 'skip meetings under 15 minutes.'",
      },
      {
        question:
          "What happens if a connected service is down when a briefing runs?",
        answer:
          "GAIA skips that source, notes it in the briefing, and includes everything else. The run is still marked completed.",
      },
      {
        question: "Can briefings be delivered to Slack or Telegram?",
        answer:
          "Yes. Route any scheduled briefing to a Slack channel, Telegram DM, or Discord server from the workflow settings.",
      },
      {
        question: "Are follow-up suggestions always shown after responses?",
        answer:
          "Yes. After every GAIA response, three contextual suggestions appear. Click one to execute immediately or use it as a starting point to edit.",
      },
    ],
    useCases: [
      {
        title: "Daily 9am briefing before opening email",
        description:
          "GAIA compiles unread urgent emails, the day's meetings, and any overdue tasks into a single briefing card delivered before you open your laptop.",
      },
      {
        title: "Weekly team status digest every Monday",
        description:
          "A scheduled workflow pulls GitHub PRs, Linear issues closed, and Slack highlights from the past week into a digest posted to a team Slack channel.",
      },
      {
        title: "Catch-up brief after returning from vacation",
        description:
          "Ask GAIA to summarize everything that happened across email, Slack, and GitHub in the last two weeks. One brief replaces hours of manual catch-up.",
      },
    ],
    relatedSlugs: ["workflows", "scheduled-automation", "smart-chat"],
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
    howItWorks: [
      {
        number: "01",
        title: "Describe what to generate in chat",
        description:
          "Write a plain description — subject, style, mood, format — in the same chat window.",
      },
      {
        number: "02",
        title: "GAIA enhances the prompt automatically",
        description:
          "The agent rewrites your description into a detailed generation prompt to improve quality and accuracy.",
      },
      {
        number: "03",
        title: "Image renders inline in the conversation",
        description:
          "The generated image appears directly in the chat bubble. Iterate by describing changes in the next message.",
      },
    ],
    faqs: [
      {
        question: "Which image models does GAIA use?",
        answer:
          "GAIA uses DALL-E 3 by default with Stable Diffusion available as an alternative. Model selection is available in settings.",
      },
      {
        question: "Can I request variations or edits to a generated image?",
        answer:
          "Yes. Reply in chat with instructions like 'make the background darker' or 'add a sunset' and GAIA re-generates with those changes applied.",
      },
      {
        question: "What aspect ratios and resolutions are supported?",
        answer:
          "Square (1:1), landscape (16:9), and portrait (9:16) at up to 1024x1024. Specify the ratio in your prompt or leave it out for the default square format.",
      },
      {
        question: "Are generated images saved anywhere?",
        answer:
          "Images are stored on the CDN and linked in the conversation. They remain accessible as long as the conversation exists.",
      },
    ],
    useCases: [
      {
        title: "Social media visuals without a designer",
        description:
          "Describe a post concept and get a matching image in seconds. Generate multiple variations in one conversation and pick the best.",
      },
      {
        title: "Mockup for a product idea",
        description:
          "Prototype a UI layout, product packaging, or app icon by describing it in plain language. Useful for early-stage product discussions.",
      },
      {
        title: "Presentation slides with custom illustrations",
        description:
          "Ask for a unique illustration per slide topic. Consistent style, correct dimensions, ready to drop into your deck.",
      },
    ],
    relatedSlugs: ["smart-chat", "rich-responses", "document-generation"],
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
    howItWorks: [
      {
        number: "01",
        title: "Ask GAIA to write or run code",
        description:
          "Describe what to compute, analyze, or build. GAIA writes the code and submits it to a sandbox automatically.",
      },
      {
        number: "02",
        title: "Code executes in an isolated E2B container",
        description:
          "The sandbox spins up in under a second. Code runs with no access to your machine or data.",
      },
      {
        number: "03",
        title: "Output and charts appear inline",
        description:
          "Stdout, errors, and any generated charts are captured and rendered directly in the conversation.",
      },
    ],
    faqs: [
      {
        question: "Which languages are supported?",
        answer:
          "Python, JavaScript, TypeScript, R, Java, and Bash. Each runs in a fresh sandbox with standard libraries available.",
      },
      {
        question: "Can I install additional packages inside the sandbox?",
        answer:
          "Yes. Ask GAIA to install a package with pip or npm at the start of the session. Packages are available for that execution but not persisted across sessions.",
      },
      {
        question: "Can the sandbox access files I upload?",
        answer:
          "Yes. Files attached to the conversation are available inside the sandbox at a predictable path. GAIA handles the mounting automatically.",
      },
      {
        question: "What happens when the code has an error?",
        answer:
          "The error message is captured and shown in the chat. GAIA reads the traceback, explains the issue, and can rewrite the code to fix it.",
      },
    ],
    useCases: [
      {
        title: "Data analysis on a CSV without Excel",
        description:
          "Upload a CSV and ask GAIA to find the top 10 rows by revenue and plot a bar chart. Python runs instantly, chart appears inline.",
      },
      {
        title: "Quick script to automate a repetitive task",
        description:
          "Describe what to automate in plain language. GAIA writes a Bash or Python script, runs it in the sandbox to verify it works, then shares the final version.",
      },
      {
        title: "Statistical analysis for a research report",
        description:
          "Feed GAIA a dataset and ask for regression analysis, correlation matrix, and a summary. R code runs, charts render, results are ready to copy into a report.",
      },
    ],
    relatedSlugs: ["smart-chat", "rich-responses", "document-generation"],
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
    faqs: [
      {
        question: "Can I interact with charts and tables directly?",
        answer:
          "Yes. Bar charts, pie charts, and timelines are interactive — hover for tooltips, click to filter. Tables support sorting by column.",
      },
      {
        question: "What triggers a rich component instead of plain text?",
        answer:
          "GAIA detects data shape automatically. Structured lists become tables, time-series data becomes charts, step sequences become timelines. No manual formatting needed.",
      },
      {
        question:
          "Are rich components available in the Slack or Telegram bots?",
        answer:
          "The full component library is available on web and desktop. Slack and Telegram receive simplified text equivalents suited to those platforms.",
      },
      {
        question: "Can I copy the underlying data from a chart or table?",
        answer:
          "Yes. Every rich component has a copy button that exports the data as CSV or JSON depending on the component type.",
      },
    ],
    useCases: [
      {
        title: "Pipeline report as an interactive table",
        description:
          "Ask GAIA to pull deals from HubSpot and show open pipeline by stage. The result is a sortable table with deal value, owner, and close date.",
      },
      {
        title: "Sprint progress as a timeline",
        description:
          "Ask for a summary of this sprint's Linear issues. GAIA returns a Gantt-style timeline with status colors and milestone markers.",
      },
      {
        title: "Tech stack comparison before a decision",
        description:
          "Ask GAIA to compare three frameworks across five criteria. The result is an interactive comparison table with pros, cons, and a recommendation.",
      },
    ],
    relatedSlugs: ["smart-chat", "deep-research", "code-execution"],
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
    howItWorks: [
      {
        number: "01",
        title: "Type a task in plain language",
        description:
          "Include priority, due date, project, and labels in the same sentence — GAIA parses all of it.",
      },
      {
        number: "02",
        title: "Task is created with all fields populated",
        description:
          "Due date, priority, project assignment, and labels are extracted and applied without any form-filling.",
      },
      {
        number: "03",
        title: "GAIA can generate a workflow to complete it",
        description:
          "For complex tasks, ask GAIA to generate sub-steps or a full automated workflow and run it with one click.",
      },
    ],
    faqs: [
      {
        question: "What natural language date formats does it understand?",
        answer:
          "It handles 'tomorrow,' 'next Monday,' 'in 5 days,' 'end of month,' and specific dates like 'March 15.' Relative expressions are resolved against your local timezone.",
      },
      {
        question: "Can I assign tasks to other people?",
        answer:
          "Yes. Include '@name' in the task description and GAIA assigns it to that team member if they are in your workspace.",
      },
      {
        question: "Do tasks sync with external tools like Linear or Asana?",
        answer:
          "Yes. Connect Linear, Asana, or Todoist and GAIA creates tasks in those tools directly from chat.",
      },
      {
        question: "Can I set recurring tasks?",
        answer:
          "Yes. Say 'every Monday' or 'first of each month' and GAIA creates a recurring task with the appropriate recurrence rule.",
      },
    ],
    useCases: [
      {
        title: "Capture action items from meeting notes",
        description:
          "Paste meeting notes and ask GAIA to extract action items as tasks. Each one is created with the right owner and due date.",
      },
      {
        title: "Daily task list from inbox priorities",
        description:
          "Ask GAIA to scan your inbox and create tasks for every email requiring follow-up. Flagged with the sender name and due by end of day.",
      },
      {
        title: "Sprint planning in under five minutes",
        description:
          "Describe the sprint goals and ask GAIA to generate a task list. It creates all tasks, assigns priorities, and organizes them by milestone.",
      },
    ],
    relatedSlugs: ["calendar", "goals", "workflows"],
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
    howItWorks: [
      {
        number: "01",
        title: "Describe the event in natural language",
        description:
          "Say 'Schedule a 1-on-1 with Sarah next Tuesday at 2pm' and GAIA handles title, time, and invite.",
      },
      {
        number: "02",
        title: "GAIA checks for conflicts and creates the event",
        description:
          "Your calendar is scanned for conflicts before the event is created in Google Calendar.",
      },
      {
        number: "03",
        title: "Meeting prep is available on demand",
        description:
          "Ask for a briefing before any event — GAIA pulls attendee context, recent emails, and open tasks.",
      },
    ],
    faqs: [
      {
        question: "Does it support Google Calendar only?",
        answer:
          "Google Calendar is fully supported with two-way sync. Outlook and Apple Calendar support is on the roadmap.",
      },
      {
        question: "Can GAIA find a time that works for multiple people?",
        answer:
          "Yes. If attendees are in your workspace, GAIA checks their calendars for mutual availability before suggesting a time.",
      },
      {
        question: "Can I reschedule or cancel an event through chat?",
        answer:
          "Yes. Say 'move my 3pm tomorrow to 4pm' and GAIA finds the event, updates the time, and notifies attendees if configured.",
      },
      {
        question:
          "Does GAIA handle timezones for events with remote participants?",
        answer:
          "Yes. Specify a participant's timezone or location and GAIA sets the event in your timezone while displaying the correct time for each attendee.",
      },
    ],
    useCases: [
      {
        title: "Book a meeting without leaving a chat",
        description:
          "Ask GAIA to schedule a 30-minute call with three colleagues next week. It finds a mutual open slot, creates the event, and sends invites.",
      },
      {
        title: "Pre-meeting research brief in 30 seconds",
        description:
          "Before a sales call, ask GAIA for a briefing. It surfaces the contact's last email, open tasks, and any notes from previous meetings.",
      },
      {
        title: "Batch-schedule a recurring weekly sync",
        description:
          "Say 'every Thursday at 10am with the design team for 45 minutes' and GAIA creates a recurring series in Google Calendar.",
      },
    ],
    relatedSlugs: ["todos", "email", "reminders"],
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
    howItWorks: [
      {
        number: "01",
        title: "Connect Gmail with one-click OAuth",
        description:
          "GAIA requests read and send permissions. No API keys or manual config required.",
      },
      {
        number: "02",
        title: "Ask GAIA to triage, summarize, or respond",
        description:
          "Describe what to do — 'summarize my unread emails' or 'reply to John saying I'll follow up Friday.'",
      },
      {
        number: "03",
        title: "Review drafts and approve before sending",
        description:
          "GAIA shows the draft inline. Confirm, edit, or discard before anything is sent.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA work with multiple Gmail accounts?",
        answer:
          "Yes. Connect multiple Gmail accounts and GAIA treats them as separate inboxes, drafting and sending from the correct account.",
      },
      {
        question: "Can GAIA send emails without my approval?",
        answer:
          "Not by default. GAIA drafts and shows a preview first. Auto-send can be enabled per workflow for specific automated use cases.",
      },
      {
        question: "How does tone matching work?",
        answer:
          "GAIA analyzes your past sent emails to learn vocabulary, sentence length, and formality level. Specify 'brief and casual' or 'formal' to override for a single draft.",
      },
      {
        question: "Can it handle email threads, not just individual messages?",
        answer:
          "Yes. GAIA reads full thread context before drafting a reply. The summary includes every message in the thread, not just the latest.",
      },
    ],
    useCases: [
      {
        title: "Inbox zero on a Monday morning",
        description:
          "Ask GAIA to summarize all unread emails, flag the urgent ones, and archive everything older than 7 days. Done in under two minutes.",
      },
      {
        title: "Bulk reply to event RSVPs",
        description:
          "Ask GAIA to reply 'yes' to all pending calendar invites from this week. It reads each thread, drafts the response, and sends after a single confirmation.",
      },
      {
        title: "Follow-up reminders from sent emails",
        description:
          "Ask GAIA to scan sent mail for emails with no reply in over 5 days and create follow-up tasks for each one.",
      },
    ],
    relatedSlugs: ["calendar", "todos", "proactive-ai"],
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
    howItWorks: [
      {
        number: "01",
        title: "Describe your goal in one sentence",
        description:
          "State the outcome — GAIA generates a structured roadmap with milestones and sub-steps automatically.",
      },
      {
        number: "02",
        title: "Review and customize the roadmap",
        description:
          "Edit, reorder, or add milestones before activating. Each node is a concrete, completable action.",
      },
      {
        number: "03",
        title: "Track progress as you complete milestones",
        description:
          "Check off nodes and GAIA updates overall completion percentage and surfaces the next step.",
      },
    ],
    faqs: [
      {
        question: "Can I create a goal from scratch instead of a template?",
        answer:
          "Yes. Type any goal in plain language and GAIA generates a custom roadmap. Templates are a starting point, not a requirement.",
      },
      {
        question: "How many milestones does GAIA generate per goal?",
        answer:
          "Typically 5 to 10 milestones, each broken into 2 to 4 sub-steps. The depth is based on goal complexity and can be adjusted after generation.",
      },
      {
        question: "Can goals be linked to tasks or calendar events?",
        answer:
          "Yes. From any milestone, create a linked todo or calendar event. Completing the task marks the milestone as done.",
      },
      {
        question: "Are goals private or shared with the workspace?",
        answer:
          "Goals are private by default. Sharing with specific workspace members is available through the goal detail page.",
      },
    ],
    useCases: [
      {
        title: "Six-month career transition plan",
        description:
          "Describe the role you are targeting and GAIA generates a roadmap covering skill gaps, portfolio projects, networking steps, and application timelines.",
      },
      {
        title: "Launch a side project in 90 days",
        description:
          "Set a goal to launch a product by a date. GAIA creates a roadmap covering validation, build, marketing, and launch milestones with deadlines.",
      },
      {
        title: "Personal fitness goal with weekly milestones",
        description:
          "State a fitness target and GAIA generates weekly workout and nutrition milestones. Check off each week to track the full journey.",
      },
    ],
    relatedSlugs: ["todos", "reminders", "workflows"],
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
    howItWorks: [
      {
        number: "01",
        title: "Set a reminder in plain language",
        description:
          "Say 'remind me every Monday at 9am to review my pipeline' and GAIA creates the recurring reminder.",
      },
      {
        number: "02",
        title: "Timezone and recurrence are applied automatically",
        description:
          "Your local timezone is used by default. Recurrence patterns like 'every weekday' are converted to cron rules.",
      },
      {
        number: "03",
        title: "Reminder fires at the scheduled time",
        description:
          "Notification appears in-app, on mobile, or via the configured bot channel at exactly the right time.",
      },
    ],
    faqs: [
      {
        question: "Can reminders be sent to Slack or Telegram?",
        answer:
          "Yes. Route any reminder to a Slack DM, Telegram message, or Discord channel from reminder settings.",
      },
      {
        question:
          "Can I set a reminder to stop after a certain number of occurrences?",
        answer:
          "Yes. Say 'remind me 10 times' or 'until December 31st' and GAIA sets the max occurrence or end date accordingly.",
      },
      {
        question: "What happens if I miss a reminder notification?",
        answer:
          "Missed reminders appear in the notifications panel with a timestamp. They are not re-sent automatically but remain visible until dismissed.",
      },
      {
        question: "Can I snooze or reschedule a reminder that already fired?",
        answer:
          "Yes. From the notification or the reminders list, select 'snooze' to delay by 15 minutes, 1 hour, or a custom time.",
      },
    ],
    useCases: [
      {
        title: "Weekly pipeline review every Monday",
        description:
          "Set one recurring reminder and GAIA fires it every Monday at 9am with a prompt to review open deals in HubSpot.",
      },
      {
        title: "Follow-up reminders for pending proposals",
        description:
          "After sending a proposal, ask GAIA to remind you in 3 business days if there has been no reply. One message, one reminder created.",
      },
      {
        title: "Daily standup prompt for the team",
        description:
          "Create a recurring reminder that posts a standup prompt to a Slack channel every weekday at 9:30am.",
      },
    ],
    relatedSlugs: ["todos", "calendar", "scheduled-automation"],
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
    howItWorks: [
      {
        number: "01",
        title: "Click pin on any message",
        description:
          "Hover any message in any conversation and click the pin icon to save it instantly.",
      },
      {
        number: "02",
        title: "Pin is stored with full context",
        description:
          "The message content, timestamp, and a link to the original conversation are saved together.",
      },
      {
        number: "03",
        title: "Browse and search all pins in one place",
        description:
          "Open the Pins panel to search, filter by date or topic, and jump back to the original conversation.",
      },
    ],
    faqs: [
      {
        question: "Can I pin tool results like charts and code outputs?",
        answer:
          "Yes. Any message in a conversation can be pinned — including rich components, code blocks, and research summaries.",
      },
      {
        question: "Are pins shared with other workspace members?",
        answer:
          "No. Pins are private to your account by default. Workspace-shared pins are not currently supported.",
      },
      {
        question: "Is there a limit to how many messages I can pin?",
        answer:
          "There is no limit. Pins are stored and indexed for full-text search regardless of volume.",
      },
      {
        question: "Can I organize pins into folders or collections?",
        answer:
          "Pins can be filtered by date and searched by keyword. Folder-based organization is on the roadmap.",
      },
    ],
    useCases: [
      {
        title: "Save a research summary for later reference",
        description:
          "Pin a deep research result so you can find it next week without re-running the query. Link back to the full conversation for context.",
      },
      {
        title: "Build a personal knowledge base from conversations",
        description:
          "Pin key facts, code snippets, and summaries from different conversations. Search them later like a personal wiki.",
      },
      {
        title: "Track decisions made in AI conversations",
        description:
          "When GAIA recommends a direction and you agree, pin that message. Revisit the decision with full context when the topic comes up again.",
      },
    ],
    relatedSlugs: ["smart-chat", "memory", "deep-research"],
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
    howItWorks: [
      {
        number: "01",
        title: "Connect your tools via integrations",
        description:
          "Link Gmail, Google Calendar, and your workflow setup. Dashboard widgets populate immediately after connection.",
      },
      {
        number: "02",
        title: "Dashboard assembles all live data in one view",
        description:
          "Five bento widgets show unread email count, today's events, open todos, active workflows, and recent conversations.",
      },
      {
        number: "03",
        title: "Launch a new chat with full context pre-loaded",
        description:
          "The composer on the dashboard starts a chat with your current context — inbox state, calendar, and tasks — already available.",
      },
    ],
    faqs: [
      {
        question: "Can I customize which widgets appear on the dashboard?",
        answer:
          "Widget visibility can be toggled in dashboard settings. Reordering and resizing are on the roadmap.",
      },
      {
        question: "How frequently do the widgets refresh?",
        answer:
          "Email and calendar widgets refresh every 60 seconds. Todos and workflows update in real time via WebSocket.",
      },
      {
        question:
          "Does the dashboard work without connecting all integrations?",
        answer:
          "Yes. Widgets for unconnected services show an empty state with a connect prompt. Other widgets still function normally.",
      },
      {
        question: "Is there a mobile version of the dashboard?",
        answer:
          "Yes. The mobile app has a touch-optimized dashboard with the same widgets in a vertically stacked layout.",
      },
    ],
    useCases: [
      {
        title: "Morning context check before starting work",
        description:
          "Open GAIA and see unread emails, today's three meetings, five overdue tasks, and two active workflows — all before opening a single other app.",
      },
      {
        title: "End-of-day review and planning",
        description:
          "Check the dashboard at 5pm to see what is open, fire off a quick GAIA message to reschedule tomorrow's tasks, and close the day cleanly.",
      },
      {
        title: "One-click access to the most pressing item",
        description:
          "The dashboard surfaces the highest-priority todo and the next calendar event. Click either to jump directly into the relevant GAIA workflow.",
      },
    ],
    relatedSlugs: ["todos", "calendar", "email"],
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
    faqs: [
      {
        question: "Can I edit a workflow after GAIA generates it?",
        answer:
          "Yes. Each step is editable — change the action, modify parameters, reorder steps, or add new ones before activating.",
      },
      {
        question: "What happens when a workflow step fails?",
        answer:
          "The workflow stops at the failed step, logs the error, and sends a notification. Previous steps that succeeded are not rolled back.",
      },
      {
        question: "Can I trigger a workflow manually instead of on a schedule?",
        answer:
          "Yes. Any workflow can be run manually from the workflows list with a single click, regardless of its configured trigger.",
      },
      {
        question: "How many workflows can I have running at once?",
        answer:
          "There is no hard cap on active workflows. Concurrent execution limits depend on your plan tier.",
      },
    ],
    useCases: [
      {
        title: "Auto-triage incoming GitHub issues",
        description:
          "When a new issue is opened, a workflow reads it, assigns a label, creates a Linear ticket, and posts a Slack notification — all in under 10 seconds.",
      },
      {
        title: "Weekly competitive intelligence digest",
        description:
          "Every Friday, a workflow searches for news about three competitors, summarizes findings, and posts a formatted digest to a Slack channel.",
      },
      {
        title: "New lead enrichment pipeline",
        description:
          "When a new HubSpot contact is created, a workflow researches the company, fills in missing fields, and assigns the contact to the right sales rep.",
      },
    ],
    relatedSlugs: ["scheduled-automation", "event-triggers", "integrations"],
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
    howItWorks: [
      {
        number: "01",
        title: "Set a schedule in plain language",
        description:
          "Tell GAIA when to run — daily at 8am, every weekday, first Monday of the month — or use the visual cron builder.",
      },
      {
        number: "02",
        title: "Attach any workflow to the schedule",
        description:
          "Select an existing workflow or create a new one and link it to the trigger.",
      },
      {
        number: "03",
        title: "GAIA runs it automatically on time",
        description:
          "Each execution fires at the scheduled time, logs the result, and notifies you of any failures.",
      },
    ],
    faqs: [
      {
        question: "What is the shortest supported schedule interval?",
        answer:
          "Every 5 minutes. Shorter intervals are not supported to prevent runaway execution costs.",
      },
      {
        question: "What happens if a scheduled run fails?",
        answer:
          "GAIA logs the failure with an error message and marks the run as failed in the execution history. It does not retry automatically — trigger a manual re-run from the history panel.",
      },
      {
        question: "Can I pause a schedule without deleting it?",
        answer:
          "Yes. Each scheduled workflow has an active/paused toggle. Pausing stops future runs but preserves the schedule and all past execution history.",
      },
      {
        question: "Does each workflow have its own timezone?",
        answer:
          "Yes. Each workflow has a timezone setting independent of your account timezone. Run one workflow at 9am New York time and another at 9am London time simultaneously.",
      },
    ],
    useCases: [
      {
        title: "Daily sales pipeline digest",
        description:
          "A sales manager schedules a 7am workflow that pulls open deals from HubSpot and new emails from high-value contacts, delivering a briefing card before the day starts.",
      },
      {
        title: "Weekly GitHub PR summary to Slack",
        description:
          "An engineering team schedules a Friday 5pm run that queries all open PRs across their repos and posts a formatted summary to their Slack #engineering channel.",
      },
      {
        title: "Monthly expense report generation",
        description:
          "An operations lead schedules a first-of-month workflow that pulls transaction data, generates a formatted PDF, and emails it to the finance team automatically.",
      },
    ],
    relatedSlugs: ["workflows", "event-triggers", "proactive-ai"],
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
    howItWorks: [
      {
        number: "01",
        title: "Connect the source app as a trigger",
        description:
          "Select Gmail, GitHub, Slack, Notion, or any connected integration as the event source.",
      },
      {
        number: "02",
        title: "Define the event condition",
        description:
          "Specify which event fires the workflow — a new email from a specific sender, a PR merge, a Slack message in a specific channel.",
      },
      {
        number: "03",
        title: "Workflow runs the moment the event fires",
        description:
          "GAIA detects the event in real time and executes the linked workflow immediately.",
      },
    ],
    faqs: [
      {
        question: "How quickly does GAIA react to an event?",
        answer:
          "Most triggers fire within seconds of the event. Gmail triggers poll every 60 seconds; webhook-based triggers like GitHub and Slack react in near real time.",
      },
      {
        question:
          "Can I filter triggers so they only fire on specific conditions?",
        answer:
          "Yes. Gmail triggers support sender, subject, and label filters. GitHub triggers support event type and branch filters. Slack triggers support channel and keyword filters.",
      },
      {
        question:
          "What happens if the same event fires while the workflow is still running?",
        answer:
          "Each event creates a separate workflow run. Concurrent runs are allowed. If you want to prevent that, set a cooldown period on the trigger.",
      },
      {
        question: "Can one event trigger multiple workflows?",
        answer:
          "Yes. Multiple workflows can listen to the same event. Each fires independently when the condition matches.",
      },
    ],
    useCases: [
      {
        title: "Auto-label and reply to support emails",
        description:
          "A support team wires a Gmail trigger so every email with 'bug' in the subject gets labeled, a task created in Linear, and an acknowledgment reply sent — all in under 10 seconds.",
      },
      {
        title: "PR merge notification to Slack",
        description:
          "A developer links a GitHub PR-merged event to a workflow that posts a formatted Slack message with the PR title, author, and a diff summary to the team channel.",
      },
      {
        title: "CRM update on new client email",
        description:
          "A salesperson connects Gmail to trigger a workflow when an email arrives from a HubSpot contact, automatically updating the contact's last-activity date and adding a note.",
      },
    ],
    relatedSlugs: ["workflows", "scheduled-automation", "integrations"],
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
    howItWorks: [
      {
        number: "01",
        title: "Ask GAIA to generate a document",
        description:
          "Request a report, spec, meeting notes, or any structured output in natural language.",
      },
      {
        number: "02",
        title: "GAIA formats and structures the content",
        description:
          "Content is organized with headings, sections, a table of contents, and proper formatting for the target file format.",
      },
      {
        number: "03",
        title: "Download or share from chat",
        description:
          "The document is uploaded to CDN and a download link appears inline in the conversation.",
      },
    ],
    faqs: [
      {
        question: "What file formats are supported?",
        answer:
          "PDF, DOCX, ODT, HTML, TXT, and EPUB. Each format supports options for fonts, margins, and paper size.",
      },
      {
        question:
          "Can GAIA generate documents from data pulled by other tools?",
        answer:
          "Yes. Ask GAIA to pull data from Gmail, Google Sheets, or any connected integration and include it in the document. The generation step happens after data retrieval.",
      },
      {
        question: "Is there a size limit on generated documents?",
        answer:
          "Documents up to approximately 50,000 words are supported. For larger outputs, generate in sections and combine manually.",
      },
      {
        question: "How long does generation take?",
        answer:
          "Most documents are ready in 10 to 30 seconds. PDF generation with complex formatting takes slightly longer than plain HTML or TXT.",
      },
    ],
    useCases: [
      {
        title: "Project status report from Slack threads",
        description:
          "A project manager asks GAIA to read the last week of Slack messages in a project channel and generate a formatted PDF status report, ready to share with stakeholders.",
      },
      {
        title: "Technical spec from a conversation",
        description:
          "An engineer describes a feature in chat, and GAIA produces a DOCX spec with an overview, requirements section, and edge cases listed, formatted for the team's template.",
      },
      {
        title: "Meeting notes auto-export",
        description:
          "After a meeting summary conversation, a consultant asks GAIA to generate an HTML version of the notes and email it to all attendees as a follow-up.",
      },
    ],
    relatedSlugs: ["workflows", "rich-responses", "email"],
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
    howItWorks: [
      {
        number: "01",
        title: "Browse or install a skill",
        description:
          "Find a skill in the built-in library, install one from a GitHub repo URL, or describe a workflow and save it as a named skill.",
      },
      {
        number: "02",
        title: "Skill is indexed into GAIA's toolkit",
        description:
          "Installed skills are available immediately — GAIA selects them automatically when a matching request comes in.",
      },
      {
        number: "03",
        title: "Invoke from any conversation or workflow",
        description:
          "Call a skill by name or just describe the task. GAIA routes to the right skill without manual selection.",
      },
    ],
    faqs: [
      {
        question: "Can I install skills from any GitHub repository?",
        answer:
          "Any public GitHub repo following the Agent Skills standard can be installed. The repo must include a skill manifest file describing the available actions.",
      },
      {
        question: "How is a custom skill different from a workflow?",
        answer:
          "A workflow is a one-time or scheduled automation for a specific task. A skill is a reusable capability invocable from any conversation or workflow step.",
      },
      {
        question: "Can I keep a custom skill private?",
        answer:
          "Yes. Skills are private by default. Publishing to the marketplace is a manual opt-in step.",
      },
      {
        question: "Do skills work inside automated workflows?",
        answer:
          "Yes. Skills are available as steps in the workflow builder — chain them with other actions or triggers.",
      },
    ],
    useCases: [
      {
        title: "Reusable email triage skill",
        description:
          "A team creates a custom skill that reads the inbox, labels emails by project, and creates Linear issues for anything flagged urgent — reused across multiple workflows.",
      },
      {
        title: "GitHub repo summarizer from community",
        description:
          "A developer installs a community skill from GitHub that fetches a repo's README, recent commits, and open issues and returns a structured summary in chat.",
      },
      {
        title: "Daily briefing skill for executives",
        description:
          "An EA builds a custom briefing skill that combines calendar, email, and Slack highlights into a single morning summary card, reused across the team.",
      },
    ],
    relatedSlugs: ["workflows", "marketplace", "integrations"],
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
    howItWorks: [
      {
        number: "01",
        title: "Pick a service to connect",
        description:
          "Browse the integrations list and click Connect next to Gmail, Slack, GitHub, Notion, or any of 47 other services.",
      },
      {
        number: "02",
        title: "Complete the OAuth flow",
        description:
          "Authorize GAIA with the minimum required permissions in the service's own auth screen.",
      },
      {
        number: "03",
        title: "All that service's tools are live",
        description:
          "GAIA immediately has access to every action for that integration — no further configuration required.",
      },
    ],
    faqs: [
      {
        question: "Do I need to manage API keys?",
        answer:
          "No. All integrations use OAuth — GAIA handles token storage and refresh automatically.",
      },
      {
        question: "Can I connect multiple accounts for the same service?",
        answer:
          "Yes. Add multiple Gmail or Google Calendar accounts and GAIA treats each as a separate inbox or calendar, acting from the correct account.",
      },
      {
        question: "What permissions does GAIA request?",
        answer:
          "Permissions are scoped to the minimum needed for each action. For Gmail that means read, compose, and send — not full account access. Permission scopes are listed on each integration's detail page.",
      },
      {
        question: "Can I revoke access to a connected service?",
        answer:
          "Yes. Disconnect any integration from the Integrations settings page. GAIA immediately loses access and stored tokens are deleted.",
      },
    ],
    useCases: [
      {
        title: "Single command across Gmail and Calendar",
        description:
          "A founder connects Gmail and Google Calendar, then asks GAIA to check for meeting requests in the inbox and block the times on the calendar — one prompt, two integrations.",
      },
      {
        title: "GitHub and Linear in one workflow",
        description:
          "An engineering lead connects GitHub and Linear, then builds a workflow that creates a Linear issue automatically whenever a PR is opened without a linked issue.",
      },
      {
        title: "HubSpot and Slack briefing",
        description:
          "A sales manager connects HubSpot and Slack, then asks GAIA for a daily briefing of deals updated yesterday — delivered to a Slack channel every morning.",
      },
    ],
    relatedSlugs: ["marketplace", "mcp-support", "custom-integrations"],
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
    howItWorks: [
      {
        number: "01",
        title: "Browse the integration marketplace",
        description:
          "Search by name, category, or use case to find community-built integrations that extend GAIA's capabilities.",
      },
      {
        number: "02",
        title: "Install in one click",
        description:
          "Click Install and the integration's tools are added to GAIA immediately — no configuration needed for most integrations.",
      },
      {
        number: "03",
        title: "Clone, modify, or publish your own",
        description:
          "Fork any community integration to customize it, or publish your own custom integration to the marketplace with one toggle.",
      },
    ],
    faqs: [
      {
        question: "Are community integrations reviewed before publishing?",
        answer:
          "Community integrations are not currently reviewed before listing, but each integration page shows install count, creator, and creation date so you can evaluate trustworthiness.",
      },
      {
        question: "Can I fork a community integration and keep it private?",
        answer:
          "Yes. Cloning an integration creates a private copy in your account. You can modify it without affecting the original or publishing it.",
      },
      {
        question: "How do I publish my own integration?",
        answer:
          "Build a custom integration in the Custom Integrations section, then toggle 'Publish to marketplace' on the integration's settings page. It becomes searchable immediately.",
      },
      {
        question: "Do I need to host anything to publish an integration?",
        answer:
          "No. GAIA hosts the integration manifest. The integration just needs to point to a reachable HTTP endpoint or MCP server.",
      },
    ],
    useCases: [
      {
        title: "Install a Notion-to-Linear sync",
        description:
          "A product team finds a community integration that syncs Notion database updates to Linear issues and installs it in under a minute, without writing any code.",
      },
      {
        title: "Publish an internal tool integration",
        description:
          "An engineering team wraps their internal deployment dashboard API as a GAIA integration and publishes it to their company's private marketplace instance.",
      },
      {
        title: "Fork and localize a community integration",
        description:
          "A developer clones a popular Shopify integration from the marketplace, adds support for a regional payment provider, and saves it as a private custom version.",
      },
    ],
    relatedSlugs: ["integrations", "custom-integrations", "mcp-support"],
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
    howItWorks: [
      {
        number: "01",
        title: "Paste the MCP server URL",
        description:
          "Enter the HTTP endpoint of any MCP-compatible server in the MCP settings panel.",
      },
      {
        number: "02",
        title: "Tools are auto-discovered and indexed",
        description:
          "GAIA reads the server's manifest, discovers all available tools, and adds them to its toolkit.",
      },
      {
        number: "03",
        title: "Use tools in chat or workflows",
        description:
          "All MCP tools are available immediately in every conversation and workflow, alongside GAIA's native tools.",
      },
    ],
    faqs: [
      {
        question: "What is MCP?",
        answer:
          "Model Context Protocol is an open standard for connecting AI agents to external tools. Any service that implements MCP can expose its capabilities to GAIA.",
      },
      {
        question: "Do MCP servers need to be publicly accessible?",
        answer:
          "Yes. The MCP server must be reachable over HTTP from GAIA's servers. Local development servers are not directly supported unless exposed via a tunnel like ngrok.",
      },
      {
        question: "How does GAIA handle authentication for MCP servers?",
        answer:
          "Servers requiring bearer tokens accept a token added during setup. OAuth-based servers are handled via spec discovery — GAIA follows the server's auth flow automatically.",
      },
      {
        question: "Are MCP tools available to subagents?",
        answer:
          "Yes. All connected MCP tools are shared across the main agent and every specialized subagent.",
      },
    ],
    useCases: [
      {
        title: "Internal search tool via MCP",
        description:
          "An engineering team wraps their internal documentation search as an MCP server and connects it to GAIA, making internal docs searchable from any conversation.",
      },
      {
        title: "Proprietary database query tool",
        description:
          "A data team exposes a read-only SQL query endpoint as an MCP server, giving GAIA the ability to fetch live production metrics directly in workflows.",
      },
      {
        title: "Third-party AI tool integration",
        description:
          "A developer connects a third-party vector search service that supports MCP, making semantic search across their knowledge base available to every GAIA workflow.",
      },
    ],
    relatedSlugs: ["integrations", "custom-integrations", "subagents"],
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
    howItWorks: [
      {
        number: "01",
        title: "Enter the endpoint URL and auth",
        description:
          "Paste the URL of any REST API or MCP server and add a bearer token or configure OAuth.",
      },
      {
        number: "02",
        title: "GAIA discovers the available tools",
        description:
          "The integration is crawled and its endpoints are auto-indexed as callable tools for GAIA's agents.",
      },
      {
        number: "03",
        title: "Use in chat, workflows, or publish",
        description:
          "Tools are live immediately in conversations and workflows. Toggle public to share on the marketplace.",
      },
    ],
    faqs: [
      {
        question: "Do I need to write code to create a custom integration?",
        answer:
          "No. Point GAIA at any reachable HTTP endpoint, add authentication, and tools are discovered automatically. No SDK or code required.",
      },
      {
        question: "What API formats are supported?",
        answer:
          "REST APIs with a discoverable schema (OpenAPI/Swagger) and MCP-compatible servers are both supported. Plain REST endpoints without a schema require manual tool definition.",
      },
      {
        question: "Can I limit who can use a custom integration?",
        answer:
          "Private integrations are only accessible to your account. Published integrations are visible to all GAIA users on the marketplace.",
      },
      {
        question: "How many custom integrations can I create?",
        answer:
          "There is no hard limit on the number of custom integrations per account. Each integration's tools count toward the total tool limit available to GAIA in a single conversation.",
      },
    ],
    useCases: [
      {
        title: "Internal ticket system integration",
        description:
          "An ops team points GAIA at their Zendesk-alternative's REST API, adds a bearer token, and immediately gains the ability to query and create tickets from chat.",
      },
      {
        title: "Proprietary analytics API in workflows",
        description:
          "A data analyst connects an internal analytics API to GAIA and builds a weekly workflow that fetches KPIs and formats them into a Slack summary automatically.",
      },
      {
        title: "Shared integration across a team",
        description:
          "A developer builds a custom integration for a niche project management tool, publishes it to the marketplace, and lets the whole team install it with one click.",
      },
    ],
    relatedSlugs: ["integrations", "marketplace", "mcp-support"],
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
    howItWorks: [
      {
        number: "01",
        title: "Ask for a contact by name or email",
        description:
          "Search for any person by name, email domain, company, or partial match in natural language.",
      },
      {
        number: "02",
        title: "GAIA searches all connected sources",
        description:
          "Gmail history, Google Contacts, and HubSpot CRM are queried simultaneously in one request.",
      },
      {
        number: "03",
        title: "Contact card appears inline in chat",
        description:
          "Results render as rich cards with name, email, phone, source badge, and CRM deal context.",
      },
    ],
    faqs: [
      {
        question: "Which contact sources does GAIA search?",
        answer:
          "Gmail email history, Google Contacts, and HubSpot CRM are supported. Adding more services is possible by connecting the relevant integration.",
      },
      {
        question: "Can GAIA search by company name?",
        answer:
          "Yes. Searching by company name returns all contacts at that company across every connected source.",
      },
      {
        question: "Can I ask GAIA to email a contact it finds?",
        answer:
          "Yes. After finding a contact, follow up with 'email them' and GAIA will draft and send the message using the email address from the contact card.",
      },
      {
        question: "Does GAIA write back to HubSpot?",
        answer:
          "Yes. Ask GAIA to update a contact's note, add a tag, or log an activity and it will write back to HubSpot via the connected integration.",
      },
    ],
    useCases: [
      {
        title: "Pre-call contact briefing in seconds",
        description:
          "Before a sales call, ask GAIA for everything on a contact — their last email thread, HubSpot deal stage, and phone number — returned as a single card in under 5 seconds.",
      },
      {
        title: "Find and email a contact from memory",
        description:
          "Ask GAIA to find the account manager at Acme Corp and send them a follow-up email. GAIA locates the contact in HubSpot and drafts the email in one step.",
      },
      {
        title: "Build a contact list for outreach",
        description:
          "Ask GAIA to list all contacts at companies in the fintech industry from HubSpot who haven't been emailed in 30 days, and create a follow-up task for each.",
      },
    ],
    relatedSlugs: ["email", "integrations", "memory"],
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
    howItWorks: [
      {
        number: "01",
        title: "Make a request involving any integration",
        description:
          "Ask GAIA to do something in GitHub, Slack, Notion, or any connected service.",
      },
      {
        number: "02",
        title: "GAIA routes to the right specialist",
        description:
          "The main agent detects which integration is needed and hands off to the dedicated subagent for that platform.",
      },
      {
        number: "03",
        title: "Specialist executes with deep platform knowledge",
        description:
          "The subagent uses scoped tools and platform-specific instructions to complete the task and return the result.",
      },
    ],
    faqs: [
      {
        question: "How many subagents are there?",
        answer:
          "There are 37 specialized subagents, one for each supported integration including Gmail, Slack, GitHub, Notion, Linear, HubSpot, Google Calendar, and more.",
      },
      {
        question: "Can multiple subagents run at the same time?",
        answer:
          "Yes. For tasks spanning multiple integrations, GAIA can run subagents in parallel — for example fetching from GitHub and Slack simultaneously — and merge the results.",
      },
      {
        question: "Can I customize a subagent's behavior?",
        answer:
          "Subagent instructions are fixed per integration to ensure reliability. Custom behaviors are handled through custom skills or workflow steps built on top of subagent outputs.",
      },
      {
        question:
          "Do subagents have access to the same memory as the main agent?",
        answer:
          "Yes. Subagents inherit the current conversation context and long-term memory from the main agent, so they know who you are and what you've asked before.",
      },
    ],
    useCases: [
      {
        title: "Cross-platform task in one message",
        description:
          "Ask GAIA to create a GitHub issue from a Slack message thread — the Slack subagent reads the thread, the GitHub subagent creates the issue, both in the same conversation.",
      },
      {
        title: "Parallel multi-source research",
        description:
          "A product manager asks for a competitive analysis. GAIA spawns Notion, Gmail, and web research subagents in parallel and combines the results into a single summary.",
      },
      {
        title: "Deep HubSpot CRM update",
        description:
          "After a sales call, ask GAIA to log the call outcome in HubSpot — the HubSpot subagent finds the contact, updates the deal stage, and adds a note, all from one instruction.",
      },
    ],
    relatedSlugs: ["integrations", "workflows", "mcp-support"],
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
    howItWorks: [
      {
        number: "01",
        title: "Activate voice mode in the app",
        description:
          "Tap the microphone button in chat to start a real-time voice session.",
      },
      {
        number: "02",
        title: "Speak and GAIA listens",
        description:
          "Deepgram transcribes your speech in near real time and sends the text to GAIA's agent.",
      },
      {
        number: "03",
        title: "GAIA responds and reads it aloud",
        description:
          "The agent completes actions and ElevenLabs TTS speaks the response back through your speaker.",
      },
    ],
    faqs: [
      {
        question: "Can GAIA take real actions in voice mode?",
        answer:
          "Yes. Voice mode has the same tool access as chat — create tasks, send emails, search the web, set reminders, and more, all hands-free.",
      },
      {
        question: "What speech-to-text engine is used?",
        answer:
          "Deepgram Nova is used for transcription, providing near real-time accuracy with low latency on most accents and languages.",
      },
      {
        question: "Can I choose a different voice for responses?",
        answer:
          "Yes. Several ElevenLabs voice profiles are available in settings. Choose from multiple accents and speaking styles.",
      },
      {
        question: "Does voice mode work on mobile?",
        answer:
          "Yes. Voice mode is fully supported on the iOS and Android mobile apps with the same capabilities as the web version.",
      },
    ],
    useCases: [
      {
        title: "Hands-free task creation while commuting",
        description:
          "A founder commutes by train and dictates tasks to GAIA hands-free — GAIA creates them with the right project and priority parsed from the spoken instruction.",
      },
      {
        title: "Quick email reply without typing",
        description:
          "A manager says 'reply to the last email from Sarah and tell her the report is ready' — GAIA drafts and sends without the user touching a keyboard.",
      },
      {
        title: "Real-time research during a walk",
        description:
          "A researcher asks GAIA about a topic while walking, receives a spoken summary, and follows up with clarifying questions — a full research session hands-free.",
      },
    ],
    relatedSlugs: ["smart-chat", "mobile", "reminders"],
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
    howItWorks: [
      {
        number: "01",
        title: "Install GAIA in your Slack workspace",
        description:
          "Add the GAIA Slack app from the integrations page with one OAuth click.",
      },
      {
        number: "02",
        title: "Mention @GAIA or use slash commands",
        description:
          "Type @GAIA in any channel with a request, or use /gaia, /todo, and /workflow commands.",
      },
      {
        number: "03",
        title: "GAIA responds and takes action",
        description:
          "Responses appear directly in the thread. Workflows can post to channels automatically on any schedule.",
      },
    ],
    faqs: [
      {
        question: "Does every team member need a GAIA account?",
        answer:
          "Each user must link their own GAIA account to Slack to use the bot. Workspace-level install allows the bot to be added, but personal account linking is required for GAIA to act on that user's data.",
      },
      {
        question: "Can GAIA post to Slack from automated workflows?",
        answer:
          "Yes. Use Slack as a workflow output step to post messages, summaries, or alerts to any channel on a schedule or when an event fires.",
      },
      {
        question: "Does @GAIA work in private channels?",
        answer:
          "Yes, as long as GAIA is invited to the private channel. Invite it like any other user.",
      },
      {
        question: "Can I use GAIA in a Slack DM?",
        answer:
          "Yes. Open a direct message with the GAIA app and use it exactly like the web chat — full tool access, memory, and context.",
      },
    ],
    useCases: [
      {
        title: "Instant GitHub PR summary in Slack",
        description:
          "A developer mentions @GAIA in the #engineering channel asking for a summary of all open PRs — GAIA queries GitHub and posts a formatted list in under 10 seconds.",
      },
      {
        title: "Daily standup briefing posted automatically",
        description:
          "A team sets up a scheduled workflow to post a morning standup summary to #general every weekday at 9am, pulling todos and calendar events for each member.",
      },
      {
        title: "Create a task from a Slack message",
        description:
          "A manager replies to a message with @GAIA create task and GAIA creates a Linear issue with the message content, priority p2, and assigns it to the sender.",
      },
    ],
    relatedSlugs: ["workflows", "integrations", "discord-bot"],
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
    howItWorks: [
      {
        number: "01",
        title: "Add GAIA bot to your Discord server",
        description:
          "Authorize the GAIA Discord app from the integrations page to install it into any server you manage.",
      },
      {
        number: "02",
        title: "Use slash commands or right-click menus",
        description:
          "Type /gaia with a request, use /todo or /workflow, or right-click any message for context menu actions.",
      },
      {
        number: "03",
        title: "GAIA responds with rich embeds",
        description:
          "Responses arrive as formatted Discord embeds with colored fields, links, and structured content.",
      },
    ],
    faqs: [
      {
        question: "Does each server member need their own GAIA account?",
        answer:
          "Yes. Each user must link their GAIA account to their Discord account. The bot can be installed server-wide, but each person acts within their own GAIA workspace.",
      },
      {
        question: "Can I use GAIA in a private Discord server?",
        answer:
          "Yes. The bot can be added to any server you have Manage Server permission for, including private or invite-only servers.",
      },
      {
        question: "What are context menus?",
        answer:
          "Right-clicking any message in Discord reveals a GAIA context menu with options like Summarize, Add as Todo, and Research This. Each option triggers the corresponding GAIA action.",
      },
      {
        question: "Can GAIA post workflow results to a Discord channel?",
        answer:
          "Yes. Use Discord as an output step in any workflow. Results, briefings, and alerts can be posted to any channel the bot has access to.",
      },
    ],
    useCases: [
      {
        title: "Community knowledge base search",
        description:
          "A Discord community installs GAIA and members use /gaia to search the community's linked Notion docs, getting answers directly in the server without leaving Discord.",
      },
      {
        title: "Summarize a long discussion thread",
        description:
          "A moderator right-clicks a long thread and selects Summarize with GAIA — a concise embed with key points appears in the channel within seconds.",
      },
      {
        title: "Automated project updates to Discord",
        description:
          "A game dev team connects GitHub to a workflow that posts a daily build status embed to their Discord #updates channel every morning at 10am.",
      },
    ],
    relatedSlugs: ["slack-bot", "telegram-bot", "workflows"],
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
    howItWorks: [
      {
        number: "01",
        title: "Start a chat with the GAIA Telegram bot",
        description:
          "Search for @GAIA_bot on Telegram and start a DM, or add it to a group chat.",
      },
      {
        number: "02",
        title: "Link your GAIA account",
        description:
          "Send /start and follow the link to connect your GAIA account — one-time setup.",
      },
      {
        number: "03",
        title: "Use commands or just type a request",
        description:
          "Use /gaia, /todo, or /workflow commands, or type any request in plain language and GAIA responds.",
      },
    ],
    faqs: [
      {
        question: "Does GAIA respond in group chats?",
        answer:
          "Yes, but responses in group chats are sent as private DMs to avoid cluttering the group. The bot acknowledges the request in the group so others can see it was received.",
      },
      {
        question: "Are Telegram messages end-to-end encrypted?",
        answer:
          "Regular Telegram chats are encrypted in transit but not end-to-end. Secret Chats are end-to-end encrypted but bots cannot participate in them. GAIA operates in regular chats only.",
      },
      {
        question: "What commands are available?",
        answer:
          "/gaia starts a conversation, /todo creates a task, /workflow runs a workflow by name. The full list appears in Telegram's / suggestion menu and updates automatically.",
      },
      {
        question: "Can I receive workflow notifications on Telegram?",
        answer:
          "Yes. Add Telegram as an output step in any workflow to receive scheduled briefings, alerts, and reports as Telegram messages.",
      },
    ],
    useCases: [
      {
        title: "Reminders on the go via Telegram",
        description:
          "A consultant sets reminders through the Telegram bot while traveling — no app switching, no desktop needed. Reminders arrive as Telegram messages at the right time.",
      },
      {
        title: "Quick task capture from anywhere",
        description:
          "A product manager sends /todo review launch checklist before 5pm Friday to the GAIA bot and the task is created immediately with the correct due date.",
      },
      {
        title: "International team workflow alerts",
        description:
          "A distributed team uses Telegram as their primary messaging app. A scheduled GAIA workflow sends daily deployment status to the team's Telegram group bot.",
      },
    ],
    relatedSlugs: ["slack-bot", "discord-bot", "mobile"],
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
    howItWorks: [
      {
        number: "01",
        title: "Download the app for iOS or Android",
        description:
          "Install GAIA from the App Store or Google Play and log in with your existing account.",
      },
      {
        number: "02",
        title: "All your data syncs instantly",
        description:
          "Conversations, todos, workflows, and integrations are all available immediately — no extra setup.",
      },
      {
        number: "03",
        title: "Use GAIA with touch, voice, or push",
        description:
          "Chat by typing or voice, manage tasks with long-press bulk select, and receive workflow completions as native push notifications.",
      },
    ],
    faqs: [
      {
        question: "Is the mobile app a full version or a lighter version?",
        answer:
          "Full version. Every feature available on web — chat, todos, workflows, integrations, voice, goals, reminders — is available on mobile with the same capabilities.",
      },
      {
        question: "Does the mobile app work offline?",
        answer:
          "Past conversations and tasks are cached locally and browsable without a connection. New requests and actions require an internet connection.",
      },
      {
        question: "Are push notifications supported?",
        answer:
          "Yes. Workflow completions, reminders, and scheduled briefings are delivered as OS-level push notifications on both iOS and Android.",
      },
      {
        question: "Is there a tablet layout?",
        answer:
          "Yes. The app adapts to iPad and Android tablets with a split-view layout showing the conversation list alongside the active chat.",
      },
    ],
    useCases: [
      {
        title: "Morning briefing on the commute",
        description:
          "An executive opens GAIA on their phone every morning to review the automated briefing — calendar, emails, and todos for the day — before arriving at the office.",
      },
      {
        title: "Voice task capture while driving",
        description:
          "A sales rep dictates new tasks and follow-up reminders to GAIA hands-free via the mobile app's voice mode while driving between client meetings.",
      },
      {
        title: "Real-time workflow notifications",
        description:
          "A developer receives a push notification the moment a scheduled deployment workflow completes, with a summary of what ran and whether it succeeded.",
      },
    ],
    relatedSlugs: ["voice", "smart-chat", "telegram-bot"],
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
