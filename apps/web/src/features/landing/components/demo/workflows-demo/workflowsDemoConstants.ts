export const DEMO_USER_WORKFLOWS = [
  {
    id: "uwf1",
    title: "Daily Email Digest",
    description:
      "Summarize important emails from today and send a digest to Slack",
    steps: [
      { id: "s1", title: "Fetch Emails", category: "gmail", description: "" },
      { id: "s2", title: "Filter", category: "executor", description: "" },
      { id: "s3", title: "Send Digest", category: "slack", description: "" },
    ],
    activated: true,
    total_executions: 45,
    trigger_type: "schedule" as const,
    trigger_label: "Daily at 9 AM",
  },
  {
    id: "uwf2",
    title: "PR Review Notifier",
    description: "Get notified on Slack when PRs need review",
    steps: [
      { id: "s1", title: "Watch PRs", category: "github", description: "" },
      { id: "s2", title: "Filter", category: "executor", description: "" },
      { id: "s3", title: "Notify", category: "slack", description: "" },
    ],
    activated: true,
    total_executions: 128,
    trigger_type: "event" as const,
    trigger_label: "On new PR",
  },
  {
    id: "uwf3",
    title: "Weekly Standup Summary",
    description: "Generate weekly standup reports from Linear and GitHub",
    steps: [
      {
        id: "s1",
        title: "Fetch Issues",
        category: "linear",
        description: "",
      },
      { id: "s2", title: "Get PRs", category: "github", description: "" },
      { id: "s3", title: "Summarize", category: "executor", description: "" },
      { id: "s4", title: "Send", category: "gmail", description: "" },
    ],
    activated: false,
    total_executions: 12,
    trigger_type: "schedule" as const,
    trigger_label: "Weekly on Monday",
  },
  {
    id: "uwf4",
    title: "Meeting Notes to Notion",
    description:
      "After each meeting, create a Notion doc with AI-generated notes",
    steps: [
      {
        id: "s1",
        title: "Detect Meeting End",
        category: "googlecalendar",
        description: "",
      },
      {
        id: "s2",
        title: "Transcribe",
        category: "executor",
        description: "",
      },
      {
        id: "s3",
        title: "Save to Notion",
        category: "notion",
        description: "",
      },
    ],
    activated: true,
    total_executions: 67,
    trigger_type: "event" as const,
    trigger_label: "After meetings",
  },
];

export const DEMO_COMMUNITY_WORKFLOWS = [
  {
    id: "cwf1",
    title: "Social Media Content Pipeline",
    description:
      "Generate, schedule, and cross-post content across Twitter and LinkedIn",
    steps: [
      {
        title: "Generate Ideas",
        category: "executor",
        description: "",
      },
      { title: "Draft Posts", category: "executor", description: "" },
      { title: "Post to Twitter", category: "twitter", description: "" },
      { title: "Post to LinkedIn", category: "linkedin", description: "" },
    ],
    creator: { id: "u1", name: "Emily Zhang", avatar: "" },
    categories: ["featured", "social"],
    total_executions: 892,
  },
  {
    id: "cwf2",
    title: "Customer Feedback Analyzer",
    description:
      "Collect feedback from email and Slack, analyze sentiment, create reports",
    steps: [
      { title: "Read Emails", category: "gmail", description: "" },
      { title: "Read Slack", category: "slack", description: "" },
      { title: "Analyze", category: "executor", description: "" },
      {
        title: "Create Doc",
        category: "googledocs",
        description: "",
      },
    ],
    creator: { id: "u2", name: "Marcus Johnson" },
    categories: ["featured", "productivity"],
    total_executions: 456,
  },
  {
    id: "cwf3",
    title: "Automated Invoice Processing",
    description: "Extract data from invoices and update spreadsheets",
    steps: [
      { title: "Read Invoice", category: "gmail", description: "" },
      { title: "Extract Data", category: "executor", description: "" },
      {
        title: "Update Sheet",
        category: "googlesheets",
        description: "",
      },
    ],
    creator: { id: "u3", name: "Lisa Park" },
    categories: ["productivity"],
    total_executions: 234,
  },
  {
    id: "cwf4",
    title: "Competitor Price Monitor",
    description: "Track competitor pricing changes and alert via Slack",
    steps: [
      { title: "Scrape Prices", category: "executor", description: "" },
      { title: "Compare", category: "executor", description: "" },
      {
        title: "Alert Slack",
        category: "slack",
        description: "",
      },
      {
        title: "Log to Sheet",
        category: "googlesheets",
        description: "",
      },
    ],
    creator: { id: "u4", name: "James Chen" },
    categories: ["business"],
    total_executions: 167,
  },
];
