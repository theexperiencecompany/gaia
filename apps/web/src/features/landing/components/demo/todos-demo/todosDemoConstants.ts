export interface DemoProject {
  id: string;
  name: string;
  color: string;
}

export interface DemoSubTask {
  id: string;
  title: string;
  completed: boolean;
}

export interface DemoWorkflowStep {
  id: string;
  title: string;
  description: string;
  category: string;
}

export interface DemoTodo {
  id: string;
  title: string;
  description?: string;
  priority: "high" | "medium" | "low" | "none";
  labels: string[];
  project_id: string;
  due_date?: string;
  completed: boolean;
  subtasks: DemoSubTask[];
  workflow_categories: string[];
  workflow_steps: DemoWorkflowStep[];
  created_at: string;
}

export const DEMO_PROJECTS: DemoProject[] = [
  { id: "inbox", name: "Inbox", color: "#71717a" },
  { id: "gaia", name: "GAIA", color: "#00bbff" },
  { id: "personal", name: "Personal", color: "#10b981" },
  { id: "marketing", name: "Marketing", color: "#f59e0b" },
];

const today = new Date();

function dayOffset(offset: number): string {
  const d = new Date(today);
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
}

function createdAgo(daysAgo: number): string {
  const d = new Date(today);
  d.setDate(d.getDate() - daysAgo);
  return d.toISOString();
}

export const DEMO_TODOS: DemoTodo[] = [
  {
    id: "td-1",
    title: "Review Series A term sheet",
    description:
      "Go through the latest term sheet from Accel and flag any concerns before the board call.",
    priority: "high",
    labels: [],
    project_id: "gaia",
    due_date: dayOffset(0),
    completed: false,
    subtasks: [
      { id: "st-1a", title: "Review financial projections", completed: true },
      { id: "st-1b", title: "Analyze dilution terms", completed: false },
      { id: "st-1c", title: "Schedule call with lawyer", completed: false },
    ],
    workflow_categories: ["gmail", "googledocs", "googlecalendar"],
    workflow_steps: [
      {
        id: "ws-1a",
        title: "Fetch term sheet email",
        description: "Pull the latest term sheet from Accel's email thread",
        category: "gmail",
      },
      {
        id: "ws-1b",
        title: "Extract key terms",
        description:
          "Parse financial projections and dilution terms from document",
        category: "googledocs",
      },
      {
        id: "ws-1c",
        title: "Schedule lawyer review",
        description: "Create calendar event for legal review call",
        category: "googlecalendar",
      },
    ],
    created_at: createdAgo(3),
  },
  {
    id: "td-2",
    title: "Fix onboarding flow bug",
    description:
      "Users are dropping off at step 3 of the onboarding wizard. Investigate and patch.",
    priority: "high",
    labels: [],
    project_id: "gaia",
    due_date: dayOffset(0),
    completed: false,
    subtasks: [],
    workflow_categories: ["github", "linear"],
    workflow_steps: [
      {
        id: "ws-2a",
        title: "Create Linear issue",
        description: "File a bug report with reproduction steps and priority",
        category: "linear",
      },
      {
        id: "ws-2b",
        title: "Create GitHub branch",
        description: "Open a feature branch for the onboarding fix",
        category: "github",
      },
      {
        id: "ws-2c",
        title: "Open pull request",
        description: "Submit PR with the fix and link to Linear issue",
        category: "github",
      },
    ],
    created_at: createdAgo(1),
  },
  {
    id: "td-3",
    title: "Reply to investor emails",
    description: "Follow up with Sequoia and Lightspeed on the latest metrics.",
    priority: "high",
    labels: [],
    project_id: "gaia",
    due_date: dayOffset(0),
    completed: false,
    subtasks: [],
    workflow_categories: ["gmail", "googlesheets"],
    workflow_steps: [
      {
        id: "ws-3a",
        title: "Pull latest metrics",
        description: "Fetch Q4 revenue and growth numbers from spreadsheet",
        category: "googlesheets",
      },
      {
        id: "ws-3b",
        title: "Draft investor update",
        description: "Compose follow-up email with metrics summary",
        category: "gmail",
      },
      {
        id: "ws-3c",
        title: "Send emails",
        description: "Send personalized updates to Sequoia and Lightspeed",
        category: "gmail",
      },
    ],
    created_at: createdAgo(2),
  },
  {
    id: "td-4",
    title: "Book flights for YC interview",
    priority: "high",
    labels: [],
    project_id: "personal",
    due_date: dayOffset(1),
    completed: false,
    subtasks: [],
    workflow_categories: ["googlecalendar", "gmail"],
    workflow_steps: [
      {
        id: "ws-4a",
        title: "Check interview schedule",
        description: "Verify YC interview date and time from calendar",
        category: "googlecalendar",
      },
      {
        id: "ws-4b",
        title: "Send booking confirmation",
        description: "Email flight details and itinerary to co-founder",
        category: "gmail",
      },
    ],
    created_at: createdAgo(4),
  },
  {
    id: "td-5",
    title: "Write Q4 blog post draft",
    description:
      "Outline key achievements and product updates for the quarterly blog post.",
    priority: "medium",
    labels: ["content", "marketing"],
    project_id: "marketing",
    due_date: dayOffset(1),
    completed: false,
    subtasks: [],
    workflow_categories: ["notion", "slack"],
    workflow_steps: [
      {
        id: "ws-5a",
        title: "Gather product updates",
        description: "Pull recent changelog entries from Notion",
        category: "notion",
      },
      {
        id: "ws-5b",
        title: "Draft blog post",
        description: "Create new Notion page with Q4 highlights outline",
        category: "notion",
      },
      {
        id: "ws-5c",
        title: "Request team review",
        description: "Post draft link in #marketing channel for feedback",
        category: "slack",
      },
    ],
    created_at: createdAgo(5),
  },
  {
    id: "td-6",
    title: "Update pitch deck with new metrics",
    priority: "medium",
    labels: [],
    project_id: "gaia",
    due_date: dayOffset(2),
    completed: false,
    subtasks: [],
    workflow_categories: ["googlesheets", "googledocs"],
    workflow_steps: [
      {
        id: "ws-6a",
        title: "Export latest metrics",
        description: "Pull revenue and user growth data from analytics sheet",
        category: "googlesheets",
      },
      {
        id: "ws-6b",
        title: "Update deck slides",
        description: "Replace metrics charts and numbers in pitch document",
        category: "googledocs",
      },
    ],
    created_at: createdAgo(6),
  },
  {
    id: "td-7",
    title: "Set up CI/CD pipeline for mobile app",
    priority: "medium",
    labels: ["infra", "devops"],
    project_id: "gaia",
    completed: false,
    subtasks: [],
    workflow_categories: ["github", "slack"],
    workflow_steps: [
      {
        id: "ws-7a",
        title: "Create GitHub Actions config",
        description: "Set up build and test workflow for React Native app",
        category: "github",
      },
      {
        id: "ws-7b",
        title: "Configure deploy steps",
        description: "Add automated deployment to TestFlight and Play Store",
        category: "github",
      },
      {
        id: "ws-7c",
        title: "Notify team",
        description: "Post CI/CD setup summary to #engineering channel",
        category: "slack",
      },
    ],
    created_at: createdAgo(7),
  },
  {
    id: "td-8",
    title: "Grocery shopping",
    priority: "low",
    labels: [],
    project_id: "personal",
    due_date: dayOffset(0),
    completed: false,
    subtasks: [],
    workflow_categories: ["notion"],
    workflow_steps: [
      {
        id: "ws-8a",
        title: "Check shopping list",
        description: "Pull items from weekly meal plan in Notion",
        category: "notion",
      },
    ],
    created_at: createdAgo(1),
  },
  {
    id: "td-9",
    title: "Plan team offsite",
    priority: "low",
    labels: [],
    project_id: "gaia",
    due_date: dayOffset(5),
    completed: false,
    subtasks: [
      { id: "st-9a", title: "Book venue", completed: false },
      { id: "st-9b", title: "Plan activities", completed: false },
      { id: "st-9c", title: "Send invites", completed: false },
    ],
    workflow_categories: ["googlecalendar", "slack", "notion"],
    workflow_steps: [
      {
        id: "ws-9a",
        title: "Research venues",
        description: "Find available venues and compare pricing in Notion",
        category: "notion",
      },
      {
        id: "ws-9b",
        title: "Create event",
        description: "Block off dates on the team calendar",
        category: "googlecalendar",
      },
      {
        id: "ws-9c",
        title: "Send invitations",
        description: "Post offsite details and RSVP link in #general",
        category: "slack",
      },
    ],
    created_at: createdAgo(8),
  },
  {
    id: "td-10",
    title: "Read Designing Data-Intensive Applications Ch. 5",
    priority: "none",
    labels: ["learning"],
    project_id: "personal",
    completed: false,
    subtasks: [],
    workflow_categories: ["notion"],
    workflow_steps: [
      {
        id: "ws-10a",
        title: "Create reading notes",
        description: "Set up a new Notion page for chapter 5 key takeaways",
        category: "notion",
      },
    ],
    created_at: createdAgo(10),
  },
  {
    id: "td-11",
    title: "Weekly meal prep",
    priority: "low",
    labels: [],
    project_id: "personal",
    completed: true,
    subtasks: [],
    workflow_categories: ["notion"],
    workflow_steps: [
      {
        id: "ws-11a",
        title: "Check meal plan",
        description: "Pull this week's recipes from Notion meal planner",
        category: "notion",
      },
    ],
    created_at: createdAgo(3),
  },
  {
    id: "td-12",
    title: "Send invoice to client",
    priority: "medium",
    labels: [],
    project_id: "marketing",
    completed: true,
    subtasks: [],
    workflow_categories: ["gmail", "googlesheets"],
    workflow_steps: [
      {
        id: "ws-12a",
        title: "Generate invoice",
        description: "Calculate totals from project hours spreadsheet",
        category: "googlesheets",
      },
      {
        id: "ws-12b",
        title: "Send to client",
        description: "Email the invoice PDF with payment details",
        category: "gmail",
      },
    ],
    created_at: createdAgo(5),
  },
];
