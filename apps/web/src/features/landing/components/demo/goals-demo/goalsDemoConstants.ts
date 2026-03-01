// ─── Types ────────────────────────────────────────────────────────────────────

export interface DemoNodeData extends Record<string, unknown> {
  id: string;
  label: string;
  details: string[];
  estimatedTime: string;
  resources: string[];
  type: string;
  isComplete: boolean;
}

// ─── Static demo data ─────────────────────────────────────────────────────────

export const GOAL_NODES_RAW: Array<{ id: string; data: DemoNodeData }> = [
  {
    id: "1",
    data: {
      id: "1",
      label: "Define MVP Scope",
      details: [
        "Write product spec",
        "Prioritise features by impact",
        "Agree on scope with team",
      ],
      estimatedTime: "3 days",
      resources: [
        "Product spec template",
        "Jobs-to-be-done framework",
        "MoSCoW prioritisation",
      ],
      type: "milestone",
      isComplete: true,
    },
  },
  {
    id: "2",
    data: {
      id: "2",
      label: "UI/UX Design",
      details: [
        "Build component library",
        "Define colour tokens",
        "Create key page wireframes",
      ],
      estimatedTime: "1 week",
      resources: [
        "Figma tokens guide",
        "Tailwind CSS docs",
        "Radix UI primitives",
      ],
      type: "task",
      isComplete: true,
    },
  },
  {
    id: "3",
    data: {
      id: "3",
      label: "Backend API",
      details: [
        "Set up FastAPI project",
        "Define REST endpoints",
        "Write OpenAPI schema",
      ],
      estimatedTime: "2 weeks",
      resources: [
        "FastAPI docs",
        "PostgreSQL best practices",
        "Pydantic v2 guide",
      ],
      type: "task",
      isComplete: true,
    },
  },
  {
    id: "4",
    data: {
      id: "4",
      label: "Agent Integration",
      details: [
        "Wire tool calling",
        "Set up memory store",
        "Test multi-step reasoning",
      ],
      estimatedTime: "1 week",
      resources: [
        "LangGraph docs",
        "Anthropic tool use guide",
        "Agent evaluation patterns",
      ],
      type: "task",
      isComplete: false,
    },
  },
  {
    id: "5",
    data: {
      id: "5",
      label: "DevOps & Infrastructure",
      details: [
        "Configure Docker Compose",
        "Set up cloud provider",
        "Configure environment secrets",
      ],
      estimatedTime: "4 days",
      resources: ["Docker docs", "Railway.app guide", "12-factor app"],
      type: "task",
      isComplete: false,
    },
  },
  {
    id: "6",
    data: {
      id: "6",
      label: "CI/CD Pipeline",
      details: [
        "Set up GitHub Actions",
        "Write test suite",
        "Automate staging deploys",
      ],
      estimatedTime: "3 days",
      resources: [
        "GitHub Actions docs",
        "pytest best practices",
        "Nx monorepo CI guide",
      ],
      type: "task",
      isComplete: false,
    },
  },
  {
    id: "7",
    data: {
      id: "7",
      label: "Integration Testing",
      details: [
        "End-to-end user flows",
        "Performance benchmarks",
        "Fix critical bugs",
      ],
      estimatedTime: "1 week",
      resources: [
        "Playwright docs",
        "k6 load testing",
        "Sentry error tracking",
      ],
      type: "milestone",
      isComplete: false,
    },
  },
  {
    id: "8",
    data: {
      id: "8",
      label: "Beta Launch",
      details: [
        "Onboard 20 beta users",
        "Collect structured feedback",
        "Triage & fix blockers",
      ],
      estimatedTime: "2 weeks",
      resources: [
        "Beta feedback template",
        "Linear bug tracking",
        "Hotjar session replay",
      ],
      type: "milestone",
      isComplete: false,
    },
  },
];

export const GOAL_EDGES = [
  { id: "e1-2", source: "1", target: "2" },
  { id: "e1-3", source: "1", target: "3" },
  { id: "e1-5", source: "1", target: "5" },
  { id: "e2-4", source: "2", target: "4" },
  { id: "e3-4", source: "3", target: "4" },
  { id: "e5-6", source: "5", target: "6" },
  { id: "e4-7", source: "4", target: "7" },
  { id: "e6-7", source: "6", target: "7" },
  { id: "e7-8", source: "7", target: "8" },
];
