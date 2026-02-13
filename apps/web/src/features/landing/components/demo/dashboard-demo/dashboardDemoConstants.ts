export const DUMMY_EMAILS = [
  {
    id: "e1",
    from: "Sarah Chen <sarah@sequoia.com>",
    subject: "Re: Series A — Follow-up from yesterday",
    time: new Date(Date.now() - 1800000).toISOString(),
    thread_id: "th_001",
  },
  {
    id: "e2",
    from: "Alex Rivera <alex@linear.app>",
    subject: "PR Review: feat/auth-refactor — 23 files changed",
    time: new Date(Date.now() - 3600000).toISOString(),
    thread_id: "th_002",
  },
  {
    id: "e3",
    from: "GitHub <notifications@github.com>",
    subject: "[gaia-app] Issue #412: Memory leak in agent loop",
    time: new Date(Date.now() - 7200000).toISOString(),
    thread_id: "th_003",
  },
  {
    id: "e4",
    from: "Stripe <notifications@stripe.com>",
    subject: "Your December payout of $12,450.00 is on the way",
    time: new Date(Date.now() - 14400000).toISOString(),
    thread_id: "th_004",
  },
  {
    id: "e5",
    from: "David Kim <david@notion.so>",
    subject: "Partnership opportunity — Notion x GAIA integration",
    time: new Date(Date.now() - 21600000).toISOString(),
    thread_id: "th_005",
  },
];

const today = new Date();
const todayStr = today.toISOString().slice(0, 10);
const tomorrow = new Date(today);
tomorrow.setDate(tomorrow.getDate() + 1);
const tomorrowStr = tomorrow.toISOString().slice(0, 10);

export const DUMMY_EVENTS = [
  {
    id: "ev1",
    summary: "Standup — Engineering",
    description: "",
    start: {
      dateTime: `${todayStr}T09:30:00`,
      timeZone: "America/New_York",
    },
    end: {
      dateTime: `${todayStr}T09:45:00`,
      timeZone: "America/New_York",
    },
    status: "confirmed" as const,
    calendarId: "primary",
    creator: { email: "aryan@gaia.com" },
    organizer: { email: "aryan@gaia.com" },
    created: today.toISOString(),
    updated: today.toISOString(),
  },
  {
    id: "ev2",
    summary: "1:1 with Sarah — Product Review",
    description: "",
    start: {
      dateTime: `${todayStr}T11:00:00`,
      timeZone: "America/New_York",
    },
    end: {
      dateTime: `${todayStr}T11:30:00`,
      timeZone: "America/New_York",
    },
    status: "confirmed" as const,
    calendarId: "primary",
    creator: { email: "sarah@gaia.com" },
    organizer: { email: "sarah@gaia.com" },
    created: today.toISOString(),
    updated: today.toISOString(),
  },
  {
    id: "ev3",
    summary: "Investor Call — Sequoia",
    description: "",
    start: {
      dateTime: `${todayStr}T14:00:00`,
      timeZone: "America/New_York",
    },
    end: {
      dateTime: `${todayStr}T15:00:00`,
      timeZone: "America/New_York",
    },
    status: "confirmed" as const,
    calendarId: "work",
    creator: { email: "aryan@gaia.com" },
    organizer: { email: "aryan@gaia.com" },
    created: today.toISOString(),
    updated: today.toISOString(),
  },
  {
    id: "ev4",
    summary: "Design Review — Mobile App",
    description: "",
    start: {
      dateTime: `${tomorrowStr}T10:00:00`,
      timeZone: "America/New_York",
    },
    end: {
      dateTime: `${tomorrowStr}T11:00:00`,
      timeZone: "America/New_York",
    },
    status: "confirmed" as const,
    calendarId: "primary",
    creator: { email: "aryan@gaia.com" },
    organizer: { email: "aryan@gaia.com" },
    created: today.toISOString(),
    updated: today.toISOString(),
  },
];

export const DUMMY_CALENDARS = [
  {
    id: "primary",
    name: "Primary",
    summary: "Primary",
    primary: true,
    backgroundColor: "#00bbff",
  },
  {
    id: "work",
    name: "Work",
    summary: "Work",
    primary: false,
    backgroundColor: "#7c3aed",
  },
];

export const DUMMY_TODOS = [
  {
    id: "td1",
    title: "Review PR #412 — auth refactor",
    description: "Alex requested review on feat/auth-refactor",
    completed: false,
    priority: "high" as const,
    due_date: todayStr,
    labels: ["engineering"],
    project_id: "proj_1",
    subtasks: [],
  },
  {
    id: "td2",
    title: "Prepare Q1 roadmap presentation",
    description: "Slides for Monday all-hands",
    completed: false,
    priority: "high" as const,
    due_date: tomorrowStr,
    labels: ["planning"],
    project_id: "proj_1",
    subtasks: [],
  },
  {
    id: "td3",
    title: "Update landing page copy",
    description: "Refresh hero section and pricing",
    completed: false,
    priority: "medium" as const,
    due_date: tomorrowStr,
    labels: ["marketing"],
    project_id: "proj_2",
    subtasks: [],
  },
  {
    id: "td4",
    title: "Fix memory leak in agent loop",
    description: "Issue #412 — reported by 3 users",
    completed: false,
    priority: "high" as const,
    due_date: todayStr,
    labels: ["bug"],
    project_id: "proj_1",
    subtasks: [],
  },
  {
    id: "td5",
    title: "Set up monitoring dashboard",
    description: "Grafana + Prometheus for API metrics",
    completed: false,
    priority: "low" as const,
    due_date: undefined,
    labels: ["infra"],
    project_id: "proj_3",
    subtasks: [],
  },
];

export const DUMMY_WORKFLOWS = [
  {
    id: "wf1",
    title: "Daily Email Digest",
    description: "Summarize important emails and send a morning digest",
    steps: [
      { id: "s1", title: "Fetch Emails", category: "gmail", description: "" },
      {
        id: "s2",
        title: "Summarize",
        category: "executor",
        description: "",
      },
      {
        id: "s3",
        title: "Post to Slack",
        category: "slack",
        description: "",
      },
    ],
    activated: true,
    total_executions: 45,
    successful_executions: 42,
  },
  {
    id: "wf2",
    title: "PR Review Notifier",
    description: "Notify on Slack when PRs need review",
    steps: [
      {
        id: "s1",
        title: "Watch PRs",
        category: "github",
        description: "",
      },
      {
        id: "s2",
        title: "Filter",
        category: "executor",
        description: "",
      },
      {
        id: "s3",
        title: "Notify",
        category: "slack",
        description: "",
      },
    ],
    activated: true,
    total_executions: 128,
    successful_executions: 126,
  },
  {
    id: "wf3",
    title: "Weekly Standup Summary",
    description: "Generate weekly standup reports from Linear and GitHub",
    steps: [
      {
        id: "s1",
        title: "Fetch Issues",
        category: "linear",
        description: "",
      },
      {
        id: "s2",
        title: "Get PRs",
        category: "github",
        description: "",
      },
      {
        id: "s3",
        title: "Summarize",
        category: "executor",
        description: "",
      },
      {
        id: "s4",
        title: "Send Report",
        category: "gmail",
        description: "",
      },
    ],
    activated: false,
    total_executions: 12,
    successful_executions: 11,
  },
];

export const DUMMY_GOALS = [
  {
    id: "g1",
    title: "Launch GAIA v2.0",
    description: "Ship the next major version with agent workflows",
    progress: 65,
    created_at: new Date(Date.now() - 2592000000).toISOString(),
    roadmap: {
      nodes: [
        { data: { isComplete: true } },
        { data: { isComplete: true } },
        { data: { isComplete: true } },
        { data: { isComplete: false } },
        { data: { isComplete: false } },
      ],
      edges: [{}],
    },
  },
  {
    id: "g2",
    title: "Reach $2M ARR",
    description: "Scale revenue to $2M annual recurring revenue",
    progress: 82,
    created_at: new Date(Date.now() - 5184000000).toISOString(),
    roadmap: {
      nodes: [
        { data: { isComplete: true } },
        { data: { isComplete: true } },
        { data: { isComplete: true } },
        { data: { isComplete: true } },
        { data: { isComplete: false } },
      ],
      edges: [{}],
    },
  },
  {
    id: "g3",
    title: "Hire 5 engineers",
    description: "Grow the engineering team for Series A",
    progress: 40,
    created_at: new Date(Date.now() - 1296000000).toISOString(),
    roadmap: {
      nodes: [
        { data: { isComplete: true } },
        { data: { isComplete: true } },
        { data: { isComplete: false } },
        { data: { isComplete: false } },
        { data: { isComplete: false } },
      ],
      edges: [{}],
    },
  },
];

export const DUMMY_CONVERSATIONS = [
  {
    conversation_id: "c1",
    title: "HN + email digest",
    description: "Generated morning briefing with top HN stories and emails",
    messageCount: 8,
    starred: true,
    updated_at: new Date(Date.now() - 3600000).toISOString(),
  },
  {
    conversation_id: "c2",
    title: "Draft investor update",
    description: "Composed Q4 investor update from metrics",
    messageCount: 12,
    starred: false,
    updated_at: new Date(Date.now() - 7200000).toISOString(),
  },
  {
    conversation_id: "c3",
    title: "Plan my week",
    description: "Created weekly plan based on calendar and todos",
    messageCount: 5,
    starred: false,
    updated_at: new Date(Date.now() - 14400000).toISOString(),
  },
  {
    conversation_id: "c4",
    title: "Research competitors",
    description: "Analyzed competitor features and pricing strategies",
    messageCount: 15,
    starred: true,
    updated_at: new Date(Date.now() - 86400000).toISOString(),
  },
  {
    conversation_id: "c5",
    title: "Book flight tickets",
    description: "Found and compared flights to SF for next week",
    messageCount: 6,
    starred: false,
    updated_at: new Date(Date.now() - 172800000).toISOString(),
  },
];
