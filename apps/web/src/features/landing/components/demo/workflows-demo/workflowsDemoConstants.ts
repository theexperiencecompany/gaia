export const DEMO_USER_WORKFLOWS = [
  {
    id: "uwf1",
    title: "Investor Update Drafter",
    description:
      "Pull metrics from spreadsheets, draft a monthly investor update email, and send it out",
    steps: [
      {
        id: "s1",
        title: "Fetch Metrics",
        category: "googlesheets",
        description: "",
      },
      {
        id: "s2",
        title: "Draft Update",
        category: "executor",
        description: "",
      },
      { id: "s3", title: "Send Email", category: "gmail", description: "" },
    ],
    activated: true,
    total_executions: 24,
    trigger_type: "schedule" as const,
    trigger_label: "Monthly on 1st",
  },
  {
    id: "uwf2",
    title: "PR & Standup Summary",
    description:
      "Aggregate open PRs and Linear issues into a daily standup summary posted to Slack",
    steps: [
      { id: "s1", title: "Fetch PRs", category: "github", description: "" },
      { id: "s2", title: "Fetch Issues", category: "linear", description: "" },
      { id: "s3", title: "Post Summary", category: "slack", description: "" },
    ],
    activated: true,
    total_executions: 183,
    trigger_type: "schedule" as const,
    trigger_label: "Daily at 9 AM",
  },
  {
    id: "uwf3",
    title: "Social Content Scheduler",
    description:
      "Read a content calendar from Sheets, then draft and queue posts to Twitter and LinkedIn",
    steps: [
      {
        id: "s1",
        title: "Read Calendar",
        category: "googlesheets",
        description: "",
      },
      {
        id: "s2",
        title: "Post to Twitter",
        category: "twitter",
        description: "",
      },
      {
        id: "s3",
        title: "Post to LinkedIn",
        category: "linkedin",
        description: "",
      },
    ],
    activated: true,
    total_executions: 97,
    trigger_type: "schedule" as const,
    trigger_label: "Daily at 8 AM",
  },
  {
    id: "uwf4",
    title: "Study Plan Builder",
    description:
      "Build a weekly study plan from your calendar availability, organize tasks in Todoist and Notion",
    steps: [
      {
        id: "s1",
        title: "Check Calendar",
        category: "googlecalendar",
        description: "",
      },
      {
        id: "s2",
        title: "Create Plan",
        category: "notion",
        description: "",
      },
      {
        id: "s3",
        title: "Add Tasks",
        category: "todoist",
        description: "",
      },
    ],
    activated: false,
    total_executions: 34,
    trigger_type: "schedule" as const,
    trigger_label: "Weekly on Sunday",
  },
  {
    id: "uwf5",
    title: "Morning Briefing",
    description:
      "Compile a morning briefing from emails and calendar events, then post highlights to Slack",
    steps: [
      { id: "s1", title: "Scan Inbox", category: "gmail", description: "" },
      {
        id: "s2",
        title: "Check Calendar",
        category: "googlecalendar",
        description: "",
      },
      { id: "s3", title: "Post Briefing", category: "slack", description: "" },
    ],
    activated: true,
    total_executions: 210,
    trigger_type: "schedule" as const,
    trigger_label: "Daily at 7 AM",
  },
  {
    id: "uwf6",
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
];
