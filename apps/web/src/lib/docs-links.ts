/**
 * docs-links.ts - marketing pages -> docs.heygaia.io cross-links.
 *
 * One mapping module for the four programmatic marketing templates
 * (`/learn`, `/compare`, `/alternative-to`, `/automate`). Each template looks
 * up its own slug in its section and renders any entries inside its existing
 * related-links section as server-rendered links. Slugs with no entry render
 * nothing. Docs URLs are absolute so they survive locale prefixes.
 */

export interface DocsGuideLink {
  readonly title: string;
  readonly url: string;
}

export const LEARN_DOCS_LINKS: Record<string, readonly DocsGuideLink[]> = {
  "agent-memory": [
    {
      title: "How GAIA Remembers",
      url: "https://docs.heygaia.io/guides/memory",
    },
  ],
  "ai-agent": [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  "ai-alignment": [
    {
      title: "Ethical AI Tools: Building Technology That Serves Users",
      url: "https://docs.heygaia.io/knowledge/privacy/ethical-ai-tools",
    },
  ],
  "ai-assistant": [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  "ai-calendar-management": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "ai-email-assistant": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "ai-email-management": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "ai-meeting-assistant": [
    {
      title: "Meeting Prep Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/meeting-prep-workflow",
    },
  ],
  "ai-orchestration": [
    {
      title: "How Does Cross-App Automation Work?",
      url: "https://docs.heygaia.io/knowledge/how/cross-app-automation",
    },
  ],
  "ai-personal-productivity": [
    {
      title: "Personal Organization with AI",
      url: "https://docs.heygaia.io/knowledge/use-cases/personal-organization",
    },
  ],
  "ai-task-prioritization": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Priority Management Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/priority-management",
    },
  ],
  "api-integration": [
    {
      title: "Connecting Integrations",
      url: "https://docs.heygaia.io/guides/connecting-integrations",
    },
  ],
  "async-communication": [
    {
      title: "Async Communication Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/async-communication",
    },
  ],
  "attention-management": [
    {
      title: "Can an AI Help Me Focus?",
      url: "https://docs.heygaia.io/knowledge/can-ai/help-with-focus",
    },
  ],
  "audit-log": [
    {
      title: "Compliance and Regulatory Considerations for AI Assistants",
      url: "https://docs.heygaia.io/knowledge/privacy/compliance",
    },
  ],
  "calendar-automation": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "cognitive-load": [
    {
      title: "How Does AI Reduce Cognitive Load?",
      url: "https://docs.heygaia.io/knowledge/how/ai-reduces-cognitive-load",
    },
  ],
  "context-awareness": [
    {
      title: "How AI Context Understanding Works",
      url: "https://docs.heygaia.io/knowledge/how/ai-context-understanding",
    },
  ],
  "context-switching": [
    {
      title: "Context Switching Reduction Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/context-switching-reduction",
    },
  ],
  "data-sovereignty": [
    {
      title: "How Does GAIA Protect Your Data?",
      url: "https://docs.heygaia.io/knowledge/how/gaia-protects-data",
    },
    {
      title: "Data Ownership: Who Really Owns Your AI Assistant's Data?",
      url: "https://docs.heygaia.io/knowledge/privacy/data-ownership",
    },
  ],
  "deep-work": [
    {
      title: "Protecting Deep Work Time",
      url: "https://docs.heygaia.io/knowledge/use-cases/deep-work",
    },
    {
      title: "Deep Work Scheduling Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/deep-work-scheduling",
    },
  ],
  "digital-executive-assistant": [
    {
      title: "Can an AI Replace an Executive Assistant?",
      url: "https://docs.heygaia.io/knowledge/can-ai/replace-executive-assistant",
    },
    {
      title: "Executive Assistant Automation Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/executive-assistant-automation",
    },
  ],
  "eisenhower-matrix": [
    {
      title: "Priority Management Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/priority-management",
    },
  ],
  "email-automation": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "email-triage": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "focus-session": [
    {
      title: "Focus Time Protection Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/focus-time-protection",
    },
  ],
  "follow-up-automation": [
    {
      title: "Can an AI Automate Follow-ups?",
      url: "https://docs.heygaia.io/knowledge/can-ai/automate-followups",
    },
    {
      title: "Email Follow-up Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/email-followup-workflow",
    },
  ],
  gdpr: [
    {
      title: "Compliance and Regulatory Considerations for AI Assistants",
      url: "https://docs.heygaia.io/knowledge/privacy/compliance",
    },
  ],
  "getting-things-done": [
    {
      title: "GAIA vs Manual Productivity Systems: Automation vs Control",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-manual-systems",
    },
  ],
  "habit-stacking": [
    {
      title: "Habit Building Workflows",
      url: "https://docs.heygaia.io/knowledge/workflows/habit-building-workflows",
    },
  ],
  "human-in-the-loop": [
    {
      title: "What is Human-in-the-Loop Automation?",
      url: "https://docs.heygaia.io/knowledge/what-is/human-in-loop-automation",
    },
  ],
  "inbox-management": [
    {
      title: "Inbox Zero Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/inbox-zero-workflow",
    },
  ],
  "inbox-zero": [
    {
      title: "Inbox Zero Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/inbox-zero-workflow",
    },
  ],
  "intent-recognition": [
    {
      title: "How Does GAIA Understand User Intent?",
      url: "https://docs.heygaia.io/knowledge/how/gaia-understands-intent",
    },
  ],
  "knowledge-worker": [
    {
      title: "GAIA for Knowledge Workers",
      url: "https://docs.heygaia.io/knowledge/use-cases/knowledge-workers",
    },
  ],
  "local-llm": [
    {
      title: "Running GAIA Locally: A Practical Guide",
      url: "https://docs.heygaia.io/knowledge/privacy/running-gaia-locally",
    },
  ],
  "mcp-model-context-protocol": [
    {
      title: "Adding MCP Integrations",
      url: "https://docs.heygaia.io/guides/adding-mcp-integrations",
    },
  ],
  "meeting-intelligence": [
    {
      title: "Meeting Prep Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/meeting-prep-workflow",
    },
  ],
  "meeting-scheduling": [
    {
      title: "Can an AI Automatically Schedule Meetings?",
      url: "https://docs.heygaia.io/knowledge/can-ai/schedule-meetings",
    },
  ],
  "no-code-automation": [
    {
      title: "Building Your First Workflow",
      url: "https://docs.heygaia.io/guides/building-workflows",
    },
  ],
  "offline-first": [
    {
      title: "Offline-Capable AI: Working Without Constant Connectivity",
      url: "https://docs.heygaia.io/knowledge/privacy/offline-capable",
    },
  ],
  "open-source-ai": [
    {
      title: "What is Open-Source AI Software?",
      url: "https://docs.heygaia.io/knowledge/what-is/open-source-ai-software",
    },
    {
      title: "Open Source vs Proprietary AI: Understanding the Difference",
      url: "https://docs.heygaia.io/knowledge/privacy/open-source-vs-proprietary",
    },
  ],
  orchestration: [
    {
      title: "How Does Cross-App Automation Work?",
      url: "https://docs.heygaia.io/knowledge/how/cross-app-automation",
    },
  ],
  "proactive-ai": [
    {
      title: "What is a Proactive AI Assistant?",
      url: "https://docs.heygaia.io/knowledge/what-is/proactive-ai-assistant",
    },
    {
      title: "How Does a Proactive AI Assistant Work?",
      url: "https://docs.heygaia.io/knowledge/how/proactive-ai-assistant-works",
    },
  ],
  "prompt-engineering": [
    {
      title: "How to Talk to GAIA",
      url: "https://docs.heygaia.io/guides/chatting-effectively",
    },
  ],
  "scheduling-automation": [
    {
      title: "Can an AI Automatically Schedule Meetings?",
      url: "https://docs.heygaia.io/knowledge/can-ai/schedule-meetings",
    },
  ],
  "self-hosting": [
    {
      title: "How Does Self-Hosting Work?",
      url: "https://docs.heygaia.io/knowledge/how/self-hosting-works",
    },
    {
      title: "Who Should Self-Host Their AI Assistant?",
      url: "https://docs.heygaia.io/knowledge/privacy/who-should-self-host",
    },
  ],
  "smart-scheduling": [
    {
      title: "Can an AI Automatically Schedule Meetings?",
      url: "https://docs.heygaia.io/knowledge/can-ai/schedule-meetings",
    },
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "task-automation": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "task-batching": [
    {
      title: "Task Batching Automation Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/task-batching-automation",
    },
  ],
  "time-blocking": [
    {
      title: "Calendar Optimization Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/calendar-optimization",
    },
  ],
  "weekly-review": [
    {
      title: "Weekly Review Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/weekly-review-workflow",
    },
  ],
  "workflow-automation": [
    {
      title: "Building Your First Workflow",
      url: "https://docs.heygaia.io/guides/building-workflows",
    },
  ],
  "workflow-orchestration": [
    {
      title: "Building Your First Workflow",
      url: "https://docs.heygaia.io/guides/building-workflows",
    },
  ],
};

export const COMPARE_DOCS_LINKS: Record<string, readonly DocsGuideLink[]> = {
  activepieces: [
    {
      title: "AI Assistants vs Automation Tools: Understanding vs Executing",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
    },
  ],
  akiflow: [
    {
      title: "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
    },
  ],
  anydo: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  "apple-reminders": [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  asana: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  bardeen: [
    {
      title: "AI Assistants vs Automation Tools: Understanding vs Executing",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
    },
  ],
  basecamp: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  cal: [
    {
      title: "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
    },
  ],
  calendly: [
    {
      title: "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
    },
  ],
  chatgpt: [
    {
      title: "GAIA vs ChatGPT: Why Conversation Isn't Enough for Productivity",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-chatgpt",
    },
  ],
  "chatgpt-enterprise": [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  "chatgpt-teams": [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  claude: [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  clickup: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  clockify: [
    {
      title: "Mastering Time Management with AI",
      url: "https://docs.heygaia.io/knowledge/use-cases/time-management",
    },
  ],
  clockwise: [
    {
      title: "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
    },
  ],
  copilot: [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  "cursor-ai": [
    {
      title: "GAIA for Software Developers",
      url: "https://docs.heygaia.io/knowledge/use-cases/developers",
    },
  ],
  deepseek: [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  discord: [
    {
      title: "Async Communication Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/async-communication",
    },
  ],
  "dot-app": [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  fantastical: [
    {
      title: "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
    },
  ],
  fathom: [
    {
      title: "Post-Meeting Follow-up Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/post-meeting-followup",
    },
  ],
  "fireflies-ai": [
    {
      title: "Post-Meeting Follow-up Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/post-meeting-followup",
    },
  ],
  focusmate: [
    {
      title: "Protecting Deep Work Time",
      url: "https://docs.heygaia.io/knowledge/use-cases/deep-work",
    },
  ],
  forest: [
    {
      title: "Protecting Deep Work Time",
      url: "https://docs.heygaia.io/knowledge/use-cases/deep-work",
    },
  ],
  "friend-pendant": [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  gemini: [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  "gemini-assistant": [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  "google-assistant": [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  "google-calendar": [
    {
      title: "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
    },
  ],
  granola: [
    {
      title: "Post-Meeting Follow-up Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/post-meeting-followup",
    },
  ],
  grok: [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  harvest: [
    {
      title: "Mastering Time Management with AI",
      url: "https://docs.heygaia.io/knowledge/use-cases/time-management",
    },
  ],
  height: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  "hey-email": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  instinct: [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  jira: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  "limitless-ai": [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  "lindy-ai": [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  linear: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  loom: [
    {
      title: "Async Communication Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/async-communication",
    },
  ],
  make: [
    {
      title: "AI Assistants vs Automation Tools: Understanding vs Executing",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
    },
  ],
  "martin-ai": [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  "mem-ai": [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  missive: [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  monday: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  motion: [
    {
      title: "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
    },
  ],
  n8n: [
    {
      title: "AI Assistants vs Automation Tools: Understanding vs Executing",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
    },
  ],
  notion: [
    {
      title: "GAIA vs Notion AI: Beyond Smart Documents to True Automation",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-notion-ai",
    },
  ],
  "notion-ai": [
    {
      title: "GAIA vs Notion AI: Beyond Smart Documents to True Automation",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-notion-ai",
    },
  ],
  "notion-calendar": [
    {
      title: "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
    },
  ],
  omi: [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  omnifocus: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  "openai-dots": [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  openclaw: [
    {
      title: "AI Assistants vs Automation Tools: Understanding vs Executing",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
    },
  ],
  "otter-ai": [
    {
      title: "Post-Meeting Follow-up Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/post-meeting-followup",
    },
  ],
  perplexity: [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  "pi-ai": [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  pipedream: [
    {
      title: "AI Assistants vs Automation Tools: Understanding vs Executing",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
    },
  ],
  poke: [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  reclaim: [
    {
      title: "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
    },
  ],
  relay: [
    {
      title: "AI Assistants vs Automation Tools: Understanding vs Executing",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
    },
  ],
  rescuetime: [
    {
      title: "Mastering Time Management with AI",
      url: "https://docs.heygaia.io/knowledge/use-cases/time-management",
    },
  ],
  "rewind-ai": [
    {
      title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
    },
  ],
  sanebox: [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  savvycal: [
    {
      title: "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
    },
  ],
  shortwave: [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  siri: [
    {
      title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
      url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
    },
  ],
  smartsheet: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  spark: [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  sunsama: [
    {
      title: "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
      url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
    },
  ],
  superhuman: [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  teams: [
    {
      title: "Async Communication Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/async-communication",
    },
  ],
  things3: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  ticktick: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  todoist: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  toggl: [
    {
      title: "Mastering Time Management with AI",
      url: "https://docs.heygaia.io/knowledge/use-cases/time-management",
    },
  ],
  trello: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  wrike: [
    {
      title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
    },
  ],
  zapier: [
    {
      title: "GAIA vs Zapier: Intelligence vs Integration",
      url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-zapier",
    },
  ],
  zoom: [
    {
      title: "Async Communication Workflow",
      url: "https://docs.heygaia.io/knowledge/workflows/async-communication",
    },
  ],
};

export const ALTERNATIVE_DOCS_LINKS: Record<string, readonly DocsGuideLink[]> =
  {
    akiflow: [
      {
        title:
          "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
      },
    ],
    anydo: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    asana: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    bardeen: [
      {
        title: "AI Assistants vs Automation Tools: Understanding vs Executing",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
      },
    ],
    basecamp: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    calendly: [
      {
        title:
          "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
      },
    ],
    chatgpt: [
      {
        title:
          "GAIA vs ChatGPT: Why Conversation Isn't Enough for Productivity",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-chatgpt",
      },
    ],
    clickup: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    clockwise: [
      {
        title:
          "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
      },
    ],
    copilot: [
      {
        title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
        url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
      },
    ],
    "dot-app": [
      {
        title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
      },
    ],
    fantastical: [
      {
        title:
          "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
      },
    ],
    "friend-pendant": [
      {
        title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
      },
    ],
    gemini: [
      {
        title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
        url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
      },
    ],
    "gemini-assistant": [
      {
        title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
        url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
      },
    ],
    "google-assistant": [
      {
        title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
        url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
      },
    ],
    "google-calendar": [
      {
        title:
          "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
      },
    ],
    "hey-email": [
      {
        title: "Managing Email",
        url: "https://docs.heygaia.io/guides/managing-email",
      },
    ],
    instinct: [
      {
        title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
      },
    ],
    jira: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    "limitless-ai": [
      {
        title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
      },
    ],
    "lindy-ai": [
      {
        title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
      },
    ],
    linear: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    make: [
      {
        title: "AI Assistants vs Automation Tools: Understanding vs Executing",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
      },
    ],
    "mem-ai": [
      {
        title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
      },
    ],
    missive: [
      {
        title: "Managing Email",
        url: "https://docs.heygaia.io/guides/managing-email",
      },
    ],
    monday: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    motion: [
      {
        title:
          "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
      },
    ],
    n8n: [
      {
        title: "AI Assistants vs Automation Tools: Understanding vs Executing",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
      },
    ],
    notion: [
      {
        title: "GAIA vs Notion AI: Beyond Smart Documents to True Automation",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-notion-ai",
      },
    ],
    "notion-ai": [
      {
        title: "GAIA vs Notion AI: Beyond Smart Documents to True Automation",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-notion-ai",
      },
    ],
    omi: [
      {
        title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
      },
    ],
    omnifocus: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    "openai-dots": [
      {
        title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
      },
    ],
    openclaw: [
      {
        title: "AI Assistants vs Automation Tools: Understanding vs Executing",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
      },
    ],
    perplexity: [
      {
        title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
        url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
      },
    ],
    pipedream: [
      {
        title: "AI Assistants vs Automation Tools: Understanding vs Executing",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
      },
    ],
    poke: [
      {
        title: "AI Agents vs AI Assistants: Autonomy vs Assistance",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-agents-vs-assistants",
      },
    ],
    reclaim: [
      {
        title:
          "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
      },
    ],
    relay: [
      {
        title: "AI Assistants vs Automation Tools: Understanding vs Executing",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-automation-tools",
      },
    ],
    sanebox: [
      {
        title: "Managing Email",
        url: "https://docs.heygaia.io/guides/managing-email",
      },
    ],
    shortwave: [
      {
        title: "Managing Email",
        url: "https://docs.heygaia.io/guides/managing-email",
      },
    ],
    siri: [
      {
        title: "Why GAIA Isn't a Chatbot: Action vs Conversation",
        url: "https://docs.heygaia.io/knowledge/comparisons/why-gaia-not-chatbot",
      },
    ],
    spark: [
      {
        title: "Managing Email",
        url: "https://docs.heygaia.io/guides/managing-email",
      },
    ],
    sunsama: [
      {
        title:
          "AI Assistants vs Calendar Apps: From Scheduling to Orchestration",
        url: "https://docs.heygaia.io/knowledge/comparisons/ai-assistant-vs-calendars",
      },
    ],
    superhuman: [
      {
        title: "Managing Email",
        url: "https://docs.heygaia.io/guides/managing-email",
      },
    ],
    things3: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    ticktick: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    todoist: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    trello: [
      {
        title: "GAIA vs Traditional Task Managers: From Lists to Intelligence",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-task-managers",
      },
    ],
    zapier: [
      {
        title: "GAIA vs Zapier: Intelligence vs Integration",
        url: "https://docs.heygaia.io/knowledge/comparisons/gaia-vs-zapier",
      },
    ],
  };

export const AUTOMATE_DOCS_LINKS: Record<string, readonly DocsGuideLink[]> = {
  "airtable-google-calendar": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "airtable-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "airtable-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "asana-clickup": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "asana-discord": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "asana-drive": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "asana-figma": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "asana-github": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "asana-jira": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "asana-linear": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "asana-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "asana-salesforce": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "asana-trello": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "asana-zoom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "calendar-notion": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "calendar-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "calendar-todoist": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "discord-google-calendar": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "discord-jira": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "discord-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
  ],
  "discord-todoist": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "discord-trello": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "drive-asana": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "drive-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "drive-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "drive-trello": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "figma-asana": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "figma-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "figma-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "github-airtable": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-asana": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-clickup": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-discord": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-drive": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-figma": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-google-calendar": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-hubspot": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-jira": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-linear": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-loom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-salesforce": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-stripe": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-teams": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-todoist": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-trello": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "github-zoom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "gmail-airtable": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "gmail-asana": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "gmail-clickup": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "gmail-discord": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
  ],
  "gmail-drive": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "gmail-figma": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "gmail-github": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "gmail-google-calendar": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "gmail-hubspot": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "gmail-jira": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "gmail-linear": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "gmail-loom": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "gmail-notion": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "gmail-salesforce": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "gmail-slack": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "gmail-stripe": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "gmail-teams": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "gmail-todoist": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "gmail-trello": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "gmail-zoom": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "google-calendar-airtable": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "google-calendar-asana": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "google-calendar-clickup": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "google-calendar-discord": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "google-calendar-drive": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "google-calendar-figma": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "google-calendar-hubspot": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "google-calendar-jira": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "google-calendar-linear": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "google-calendar-loom": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "google-calendar-salesforce": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "google-calendar-stripe": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "google-calendar-teams": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "google-calendar-trello": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "google-calendar-zoom": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "hubspot-asana": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "hubspot-drive": [
    {
      title: "Building Your First Workflow",
      url: "https://docs.heygaia.io/guides/building-workflows",
    },
  ],
  "hubspot-gmail": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "hubspot-google-calendar": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "hubspot-linear": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "hubspot-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "hubspot-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "hubspot-zoom": [
    {
      title: "Building Your First Workflow",
      url: "https://docs.heygaia.io/guides/building-workflows",
    },
  ],
  "jira-airtable": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-asana": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-clickup": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-discord": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-drive": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-figma": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-github": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-google-calendar": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-hubspot": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-linear": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-loom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-salesforce": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-stripe": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-teams": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-todoist": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-trello": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "jira-zoom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-airtable": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-asana": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-clickup": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-discord": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-drive": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-figma": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-github": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-hubspot": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-jira": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-loom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-salesforce": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-stripe": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-teams": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-todoist": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-trello": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "linear-zoom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-airtable": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-asana": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-clickup": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-discord": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-drive": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-figma": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-github": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-google-calendar": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-hubspot": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-jira": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-linear": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-loom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-salesforce": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-stripe": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-teams": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-todoist": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-trello": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "notion-zoom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "salesforce-asana": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "salesforce-drive": [
    {
      title: "Building Your First Workflow",
      url: "https://docs.heygaia.io/guides/building-workflows",
    },
  ],
  "salesforce-gmail": [
    {
      title: "Managing Email",
      url: "https://docs.heygaia.io/guides/managing-email",
    },
  ],
  "salesforce-google-calendar": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "salesforce-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "salesforce-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "slack-airtable": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "slack-asana": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "slack-clickup": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "slack-discord": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
  ],
  "slack-drive": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "slack-figma": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "slack-github": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "slack-google-calendar": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "slack-hubspot": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "slack-jira": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "slack-linear": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "slack-loom": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "slack-notion": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "slack-salesforce": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "slack-stripe": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "slack-teams": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "slack-todoist": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "slack-trello": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "slack-zoom": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "stripe-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "stripe-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "teams-asana": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "teams-github": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "teams-google-calendar": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "teams-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "teams-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "todoist-airtable": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-asana": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-clickup": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-discord": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-drive": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-figma": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-github": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-google-calendar": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-hubspot": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-jira": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-linear": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-loom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-salesforce": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-stripe": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-teams": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-trello": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "todoist-zoom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "trello-discord": [
    {
      title: "Using GAIA on Discord",
      url: "https://docs.heygaia.io/guides/discord-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "trello-drive": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "trello-figma": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "trello-github": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "trello-google-calendar": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "trello-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "trello-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "trello-zoom": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "zoom-asana": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "zoom-clickup": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "zoom-drive": [
    {
      title: "Building Your First Workflow",
      url: "https://docs.heygaia.io/guides/building-workflows",
    },
  ],
  "zoom-figma": [
    {
      title: "Building Your First Workflow",
      url: "https://docs.heygaia.io/guides/building-workflows",
    },
  ],
  "zoom-google-calendar": [
    {
      title: "How Does AI Calendar Scheduling Work?",
      url: "https://docs.heygaia.io/knowledge/how/ai-calendar-scheduling",
    },
  ],
  "zoom-hubspot": [
    {
      title: "Building Your First Workflow",
      url: "https://docs.heygaia.io/guides/building-workflows",
    },
  ],
  "zoom-jira": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "zoom-linear": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "zoom-notion": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
  "zoom-slack": [
    {
      title: "Using GAIA in Slack",
      url: "https://docs.heygaia.io/guides/slack-bot",
    },
  ],
  "zoom-teams": [
    {
      title: "Building Your First Workflow",
      url: "https://docs.heygaia.io/guides/building-workflows",
    },
  ],
  "zoom-todoist": [
    {
      title: "Managing Tasks & Todos",
      url: "https://docs.heygaia.io/guides/tasks-todos",
    },
  ],
};
