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
  workflow_categories?: string[];
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
    workflow_categories: ["gmail"],
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
    created_at: createdAgo(5),
  },
];
