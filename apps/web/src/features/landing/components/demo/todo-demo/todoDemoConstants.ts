// ─── Todo Demo Types ───────────────────────────────────────────────────────

export type TodoDemoPhase =
  | "idle"
  | "modal_appear"
  | "modal_submit"
  | "todos_appear"
  | "todo_highlighted"
  | "workflow_appear"
  | "workflow_ready"
  | "run_click"
  | "executing"
  | "todo_complete"
  | "done";

// ─── Timings (ms from cycle start) ────────────────────────────────────────

export const TODO_TIMINGS = {
  modalAppear: 500,
  modalSubmit: 4000,
  todosAppear: 4900,
  todoHighlighted: 6600,
  workflowAppear: 7400,
  workflowReady: 8900,
  runClick: 9700,
  executing: 10200,
  todoComplete: 13500,
  done: 14500,
  loop: 18000,
};

// ─── Animation helpers (identical to workflow demo) ────────────────────────

export const tdEase = [0.32, 0.72, 0, 1] as const;
export const tdTx = { duration: 0.22, ease: tdEase };
export const tdSlideUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

// ─── Mock todos list ───────────────────────────────────────────────────────

export const DEMO_TODOS = [
  {
    id: "t1",
    title: "Prepare Q3 investor pitch deck",
    description: "Research pitch formats, compile data, create slide deck.",
    priority: "high" as const,
    labels: ["work"],
    project: "Work",
    dueDate: "Tomorrow",
    workflowCategories: ["executor", "googledocs", "slack"],
    subtasks: [
      { id: "st1", title: "Research pitch formats", completed: false },
      { id: "st2", title: "Compile competitor data", completed: false },
      { id: "st3", title: "Create Google Doc slides", completed: false },
    ],
    isTarget: true,
  },
  {
    id: "t2",
    title: "Review and merge PR #234",
    description: null,
    priority: "medium" as const,
    labels: ["dev"],
    project: null,
    dueDate: "Today",
    workflowCategories: [],
    subtasks: [],
    isTarget: false,
  },
  {
    id: "t3",
    title: "Schedule team retrospective",
    description: null,
    priority: "low" as const,
    labels: ["meetings"],
    project: null,
    dueDate: "Friday",
    workflowCategories: [],
    subtasks: [],
    isTarget: false,
  },
  {
    id: "t4",
    title: "Update API documentation",
    description: null,
    priority: "medium" as const,
    labels: ["dev"],
    project: null,
    dueDate: "Next week",
    workflowCategories: [],
    subtasks: [],
    isTarget: false,
  },
  {
    id: "t5",
    title: "Book team offsite venue",
    description: null,
    priority: "high" as const,
    labels: ["planning"],
    project: null,
    dueDate: "Mon",
    workflowCategories: [],
    subtasks: [],
    isTarget: false,
  },
];

export const TARGET_TODO = DEMO_TODOS.find((t) => t.isTarget)!;

// ─── Mock workflow for the target todo ────────────────────────────────────

export const DEMO_TODO_WORKFLOW = {
  steps: [
    {
      id: "ws1",
      title: "Research pitch deck best practices",
      description: "Find top-performing Q3 pitch structures via web search.",
      category: "executor",
    },
    {
      id: "ws2",
      title: "Compile competitor analysis",
      description: "Pull recent market data and summarize key differentiators.",
      category: "executor",
    },
    {
      id: "ws3",
      title: "Create slide deck in Google Docs",
      description: "Generate structured slides with sections per findings.",
      category: "googledocs",
    },
    {
      id: "ws4",
      title: "Share draft with team on Slack",
      description: "Post link to #pitch-prep channel for async review.",
      category: "slack",
    },
  ],
  toolCalls: [
    { category: "executor", message: "Researching pitch structures…" },
    { category: "executor", message: "Compiling competitor data…" },
    { category: "googledocs", message: "Creating slide deck…" },
    { category: "slack", message: "Posting to #pitch-prep" },
  ],
};

// ─── Priority styling helpers ──────────────────────────────────────────────

export const PRIORITY_RING: Record<string, string> = {
  high: "border-red-500",
  medium: "border-yellow-500",
  low: "border-blue-500",
};

export const PRIORITY_CHIP: Record<string, string> = {
  high: "text-red-400 bg-red-400/10",
  medium: "text-yellow-400 bg-yellow-400/10",
  low: "text-blue-400 bg-blue-400/10",
};
