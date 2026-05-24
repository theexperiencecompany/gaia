import type { FeatureData } from "../featuresData";

export const AI_INTELLIGENCE_FEATURES: FeatureData[] = [
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
];
