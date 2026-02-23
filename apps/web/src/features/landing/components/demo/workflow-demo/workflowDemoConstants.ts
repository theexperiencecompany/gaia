// ─── Workflow Demo Types ──────────────────────────────────────────────────────

export type WorkflowDemoPhase =
  | "idle"
  | "modal_appear"
  | "trigger_config"
  | "schedule_set"
  | "steps_generating"
  | "modal_close"
  | "card_appear"
  | "execution_start"
  | "tool_calls"
  | "execution_response"
  | "execution_complete"
  | "publish_button"
  | "publish_click"
  | "community_cards"
  | "done";

// ─── Animation timings (ms from start of cycle) ──────────────────────────────

export const WORKFLOW_TIMINGS = {
  modalAppear: 400,
  triggerConfig: 1200,
  scheduleSet: 2000,
  stepsGenerating: 3200,
  modalClose: 4600,
  cardAppear: 5200,
  executionStart: 5500,
  toolCalls: 5800,
  executionResponse: 8000,
  executionComplete: 10000,
  publishButton: 10800,
  publishClick: 11600,
  communityCards: 12200,
  done: 14400,
  loop: 17000,
};

// ─── Animation helpers ────────────────────────────────────────────────────────

export const wfEase = [0.32, 0.72, 0, 1] as const;
export const wfTx = { duration: 0.22, ease: wfEase };
export const wfSlideUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

// ─── Mock workflow data ───────────────────────────────────────────────────────

export const DEMO_WORKFLOW = {
  title: "Daily Email Digest & Briefing",
  description:
    "Every morning at 9 AM, scan my inbox for unread emails from the past 24 hours. Use AI to summarize the key points and extract action items. Create a formatted briefing document in Google Docs with sections for urgent items, meetings, and general updates. Finally, post the top 3-5 action items to our #daily-briefing Slack channel so the team stays aligned.",
  triggerType: "schedule" as const,
  cronExpression: "0 9 * * *",
  cronHumanReadable: "Every day at 9:00 AM",
  timezone: "America/New_York",
  steps: [
    {
      id: "step_1",
      title: "Fetch unread emails",
      description:
        "Read all unread emails from the last 24 hours via Gmail API.",
      category: "gmail",
    },
    {
      id: "step_2",
      title: "Summarize email contents",
      description:
        "Use LLM to generate concise summaries and extract action items.",
      category: "executor",
    },
    {
      id: "step_3",
      title: "Create briefing document",
      description:
        "Write a formatted briefing in Google Docs with sections per priority.",
      category: "googledocs",
    },
    {
      id: "step_4",
      title: "Post action items to Slack",
      description: "Send extracted action items to #daily-briefing channel.",
      category: "slack",
    },
  ],
  tools: [
    {
      category: "gmail",
      name: "gmail_list_emails",
      message: "Reading 23 unread emails",
    },
    {
      category: "executor",
      name: "executor",
      message: "Summarizing contents",
    },
    {
      category: "googledocs",
      name: "docs_create",
      message: "Creating briefing doc",
    },
    {
      category: "slack",
      name: "slack_post_message",
      message: "Posting to #daily-briefing",
    },
  ],
  executionResponse:
    "Your morning briefing is ready. 23 emails processed \u2014 4 urgent action items posted to Slack, full briefing doc created.",
};

// ─── Community workflow cards ─────────────────────────────────────────────────

export const COMMUNITY_WORKFLOWS = [
  {
    title: "PR Review & Slack Standup",
    description: "Summarize open PRs, post standup to Slack every morning.",
    categories: ["github", "slack", "executor"],
    schedule: "Every weekday at 9:30 AM",
    executions: 342,
    creator: {
      name: "Sarah Chen",
      avatar: "https://github.com/aryanranderiya.png",
    },
  },
  {
    title: "Social Content Scheduler",
    description: "Draft social posts from blog content and schedule them.",
    categories: ["notion", "executor", "slack"],
    schedule: "Every Monday at 10:00 AM",
    executions: 156,
    creator: {
      name: "Marcus Rivera",
      avatar: "https://github.com/dhruv-maradiya.png",
    },
  },
  {
    title: "Meeting Notes & Follow-ups",
    description: "Transcribe meetings, extract action items, assign tasks.",
    categories: ["googlecalendar", "googledocs", "gmail"],
    schedule: "After every meeting",
    executions: 891,
    creator: {
      name: "Aiko Tanaka",
      avatar: "https://github.com/theexperiencecompany.png",
    },
  },
];
