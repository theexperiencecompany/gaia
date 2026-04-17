/**
 * Canonical OpenUI samples for the /openui-demo preview pages.
 *
 * Both web and mobile import this list so the two demo screens render
 * the exact same component calls and can be compared side-by-side.
 */

export interface OpenUISample {
  name: string;
  group:
    | "Layout & Data"
    | "Analytics"
    | "Content"
    | "Timeline & Notifications"
    | "Code"
    | "Documents";
  code: string;
}

export const OPENUI_SAMPLES: OpenUISample[] = [
  // ---------------------------------------------------------------------------
  // Layout & Data
  // ---------------------------------------------------------------------------
  {
    name: "DataCard",
    group: "Layout & Data",
    code: `root = DataCard("Server metrics", [
  {"label": "Region", "value": "us-east-1"},
  {"label": "Instance", "value": "m7g.large"},
  {"label": "Uptime", "value": "14d 3h"},
  {"label": "Status", "value": "healthy"}
])`,
  },
  {
    name: "ResultList",
    group: "Layout & Data",
    code: `root = ResultList([
  {"title": "Design review for onboarding", "subtitle": "Due Friday", "body": "Focus on the empty state.", "badge": "design"},
  {"title": "Ship v2.1 release notes", "subtitle": "Draft ready", "url": "https://example.com/notes"},
  {"title": "Sync with platform team"}
], "Upcoming work")`,
  },
  {
    name: "ComparisonTable",
    group: "Layout & Data",
    code: `root = ComparisonTable("Starter", "Pro", [
  {"label": "Seats", "left": "3", "right": "Unlimited"},
  {"label": "SSO", "left": "no", "right": "yes", "highlight": true},
  {"label": "Audit log", "left": "no", "right": "yes"},
  {"label": "Priority support", "left": "no", "right": "yes"}
], "Plan comparison")`,
  },
  {
    name: "StatusCard",
    group: "Layout & Data",
    code: `root = StatusCard("Deployment pipeline", "success", "All 12 services deployed", "Finished in 4m 37s")`,
  },
  {
    name: "ActionCard",
    group: "Layout & Data",
    code: `root = ActionCard("Finish setting up GAIA", "One more step and you're ready to go.", [
  {"label": "Connect Gmail", "type": "continue_conversation", "value": "Connect my Gmail account"},
  {"label": "Connect Calendar", "type": "continue_conversation", "value": "Connect my Google Calendar"}
])`,
  },
  {
    name: "TagGroup",
    group: "Layout & Data",
    code: `root = TagGroup([
  {"label": "design", "color": "primary"},
  {"label": "urgent", "color": "danger"},
  {"label": "review", "color": "warning"},
  {"label": "approved", "color": "success"},
  {"label": "draft"}
], "Labels")`,
  },
  {
    name: "FileTree",
    group: "Layout & Data",
    code: `root = FileTree([
  {"path": "src/app/layout.tsx", "type": "file", "size": "2.1 KB"},
  {"path": "src/app/page.tsx", "type": "file", "size": "4.8 KB"},
  {"path": "src/components/Button.tsx", "type": "file", "size": "1.2 KB"},
  {"path": "src/components/Card.tsx", "type": "file", "size": "900 B"},
  {"path": "src/hooks/useAuth.ts", "type": "file", "size": "1.8 KB"},
  {"path": "package.json", "type": "file", "size": "3.4 KB"}
], "Project files")`,
  },
  {
    name: "Accordion",
    group: "Layout & Data",
    code: `root = Accordion([
  {"label": "What is GAIA?", "content": "GAIA is your proactive personal AI assistant."},
  {"label": "How is my data stored?", "content": "End-to-end encrypted. You control retention."},
  {"label": "Can I cancel any time?", "content": "Yes, directly from settings with no lock-in."}
], "FAQ")`,
  },
  {
    name: "TabsBlock",
    group: "Layout & Data",
    code: `root = TabsBlock([
  {"label": "Overview", "content": "A quick summary of what this project does and why it matters."},
  {"label": "Setup", "content": "Install dependencies, configure env vars, and run the dev server."},
  {"label": "Deploy", "content": "Push to main and the CI pipeline handles the rest."}
])`,
  },
  {
    name: "ProgressList",
    group: "Layout & Data",
    code: `root = ProgressList([
  {"label": "CPU", "value": 42, "color": "primary"},
  {"label": "Memory", "value": 78, "color": "warning"},
  {"label": "Disk", "value": 91, "color": "danger"},
  {"label": "Network", "value": 15, "color": "success"}
], "System usage")`,
  },
  {
    name: "SelectableList",
    group: "Layout & Data",
    code: `root = SelectableList([
  {"label": "Breakfast meeting", "description": "9:00 AM tomorrow", "value": "breakfast", "badge": "work"},
  {"label": "Gym", "description": "6:00 PM today", "value": "gym", "badge": "personal"},
  {"label": "Weekly review", "description": "Friday 4:00 PM", "value": "review"}
], "Pick an event", "Select which one to edit")`,
  },
  {
    name: "AvatarList",
    group: "Layout & Data",
    code: `root = AvatarList([
  {"name": "Dhruv Maradiya", "role": "Founder", "initials": "DM", "color": "#00bbff"},
  {"name": "Aria Chen", "role": "Designer", "initials": "AC", "color": "#f472b6"},
  {"name": "Sam Park", "role": "Engineer", "initials": "SP", "color": "#34d399"}
], "Team")`,
  },
  {
    name: "KbdBlock",
    group: "Layout & Data",
    code: `root = KbdBlock([
  {"keys": ["⌘", "K"], "description": "Open command palette"},
  {"keys": ["⌘", "⇧", "P"], "description": "Switch project"},
  {"keys": ["⌘", "/"], "description": "Toggle comment"},
  {"keys": ["esc"], "description": "Close overlay"}
], "Shortcuts")`,
  },

  // ---------------------------------------------------------------------------
  // Analytics
  // ---------------------------------------------------------------------------
  {
    name: "StatRow",
    group: "Analytics",
    code: `root = StatRow("Monthly revenue", 48200, "USD", "up", "+12% vs last month")`,
  },
  {
    name: "BarChart",
    group: "Analytics",
    code: `root = BarChart([
  {"month": "Jan", "revenue": 32},
  {"month": "Feb", "revenue": 41},
  {"month": "Mar", "revenue": 38},
  {"month": "Apr", "revenue": 52},
  {"month": "May", "revenue": 47},
  {"month": "Jun", "revenue": 63}
], "month", "revenue", "Revenue by month", "First half 2026")`,
  },
  {
    name: "LineChart",
    group: "Analytics",
    code: `root = LineChart([
  {"day": "Mon", "active": 120, "new": 35},
  {"day": "Tue", "active": 145, "new": 42},
  {"day": "Wed", "active": 132, "new": 28},
  {"day": "Thu", "active": 168, "new": 51},
  {"day": "Fri", "active": 180, "new": 47},
  {"day": "Sat", "active": 122, "new": 22},
  {"day": "Sun", "active": 98, "new": 18}
], "day", ["active", "new"], "Weekly active users", "7-day window")`,
  },
  {
    name: "AreaChart",
    group: "Analytics",
    code: `root = AreaChart([
  {"week": "W1", "signups": 45},
  {"week": "W2", "signups": 62},
  {"week": "W3", "signups": 58},
  {"week": "W4", "signups": 81},
  {"week": "W5", "signups": 95},
  {"week": "W6", "signups": 104}
], "week", "signups", "Signups over time")`,
  },
  {
    name: "PieChart",
    group: "Analytics",
    code: `root = PieChart([
  {"segment": "Mobile", "share": 52},
  {"segment": "Desktop", "share": 31},
  {"segment": "Tablet", "share": 12},
  {"segment": "Other", "share": 5}
], "segment", "share", "Traffic share")`,
  },
  {
    name: "ScatterChart",
    group: "Analytics",
    code: `root = ScatterChart([
  {"ttl": 12, "cost": 4.2},
  {"ttl": 18, "cost": 6.8},
  {"ttl": 24, "cost": 9.1},
  {"ttl": 30, "cost": 14.3},
  {"ttl": 36, "cost": 11.7},
  {"ttl": 42, "cost": 17.9}
], "ttl", "cost", "Cost vs TTL")`,
  },
  {
    name: "RadarChart",
    group: "Analytics",
    code: `root = RadarChart([
  {"axis": "Speed", "you": 85, "peers": 72},
  {"axis": "Quality", "you": 92, "peers": 80},
  {"axis": "Focus", "you": 70, "peers": 78},
  {"axis": "Impact", "you": 88, "peers": 65},
  {"axis": "Growth", "you": 76, "peers": 74}
], "axis", ["you", "peers"], "Performance snapshot")`,
  },
  {
    name: "GaugeChart",
    group: "Analytics",
    code: `root = GaugeChart(73, "CPU utilization", 0, 100, "%")`,
  },

  // ---------------------------------------------------------------------------
  // Content
  // ---------------------------------------------------------------------------
  {
    name: "ImageBlock",
    group: "Content",
    code: `root = ImageBlock("https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=800", "Mountain lake at sunrise", "Lake Braies, Italian Dolomites")`,
  },
  {
    name: "ImageGallery",
    group: "Content",
    code: `root = ImageGallery([
  {"src": "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=600", "alt": "Mountain lake"},
  {"src": "https://images.unsplash.com/photo-1470770841072-f978cf4d019e?w=600", "alt": "Alpine village"},
  {"src": "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=600", "alt": "Forest path"},
  {"src": "https://images.unsplash.com/photo-1501785888041-af3ef285b470?w=600", "alt": "Ocean cliffs"}
])`,
  },
  {
    name: "VideoBlock",
    group: "Content",
    code: `root = VideoBlock("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Demo video")`,
  },
  {
    name: "AudioPlayer",
    group: "Content",
    code: `root = AudioPlayer("https://cdn.pixabay.com/download/audio/2022/10/25/audio_31a1a0463a.mp3", "Ambient loop", "2-minute loop for focused work")`,
  },
  {
    name: "MapBlock",
    group: "Content",
    code: `root = MapBlock(46.6955, 11.8788, "Lake Braies, Italy", 13)`,
  },
  {
    name: "CalendarMini",
    group: "Content",
    code: `root = CalendarMini([
  {"date": "2026-04-18", "label": "Design review", "color": "success"},
  {"date": "2026-04-22", "label": "Launch prep", "color": "warning"},
  {"date": "2026-04-28", "label": "Cycle close", "color": "danger"}
], "April")`,
  },
  {
    name: "NumberTicker",
    group: "Content",
    code: `root = NumberTicker(12847, "Active users today", "users")`,
  },
  {
    name: "Carousel",
    group: "Content",
    code: `root = Carousel([
  {"title": "Introducing GAIA", "body": "A proactive personal AI assistant.", "image": "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=800", "badge": "new"},
  {"title": "Workflows", "body": "Turn recurring tasks into triggers.", "image": "https://images.unsplash.com/photo-1470770841072-f978cf4d019e?w=800"},
  {"title": "Voice-first", "body": "Talk to GAIA naturally.", "image": "https://images.unsplash.com/photo-1501785888041-af3ef285b470?w=800"}
])`,
  },
  {
    name: "TreeView",
    group: "Content",
    code: `root = TreeView([
  {"id": "1", "label": "Projects", "children": [
    {"id": "1a", "label": "GAIA", "description": "Personal AI", "children": [
      {"id": "1a1", "label": "Web"},
      {"id": "1a2", "label": "Mobile"}
    ]},
    {"id": "1b", "label": "Internal tools"}
  ]},
  {"id": "2", "label": "Docs"}
], "Workspace")`,
  },

  // ---------------------------------------------------------------------------
  // Timeline & Notifications
  // ---------------------------------------------------------------------------
  {
    name: "Timeline",
    group: "Timeline & Notifications",
    code: `root = Timeline([
  {"time": "09:14", "title": "Payment received", "description": "Stripe processed $49.00", "status": "success"},
  {"time": "10:02", "title": "Invoice sent", "description": "PDF emailed to client"},
  {"time": "11:45", "title": "Reconciliation failed", "description": "Mismatch on line 3", "status": "error"},
  {"time": "12:10", "title": "Retry scheduled", "status": "warning"}
], "Billing activity")`,
  },
  {
    name: "AlertBanner",
    group: "Timeline & Notifications",
    code: `root = AlertBanner("warning", "API rate limit approaching", "You've used 82% of your hourly budget. Requests will be throttled at 100%.")`,
  },
  {
    name: "Steps",
    group: "Timeline & Notifications",
    code: `root = Steps([
  {"title": "Install the CLI", "description": "pnpm install -g @gaia/cli", "status": "complete"},
  {"title": "Authenticate", "description": "Run gaia login", "status": "complete"},
  {"title": "Initialize the project", "description": "gaia init in your repo", "status": "active"},
  {"title": "Deploy", "description": "Push to main", "status": "pending"}
], "Getting started")`,
  },

  // ---------------------------------------------------------------------------
  // Code
  // ---------------------------------------------------------------------------
  {
    name: "CodeDiff",
    group: "Code",
    code: `root = CodeDiff(
  "utils.ts",
  "export function add(a: number, b: number) {\\n  return a + b;\\n}",
  "export function add(a: number, b: number): number {\\n  if (Number.isNaN(a) || Number.isNaN(b)) return 0;\\n  return a + b;\\n}",
  "Harden the add helper"
)`,
  },

  // ---------------------------------------------------------------------------
  // Documents
  // ---------------------------------------------------------------------------
  {
    name: "TextDocument",
    group: "Documents",
    code: `root = TextDocument(
  "Q2 roadmap draft",
  "# Q2 roadmap\\n\\nWe will focus on three pillars.\\n\\n**1. Reliability** — cut p99 latency by half.\\n\\n**2. Growth** — launch referral loop.\\n\\n**3. Mobile parity** — ship OpenUI on mobile.",
  [
    {"label": "Author", "value": "Dhruv"},
    {"label": "Status", "value": "Draft"},
    {"label": "Due", "value": "Apr 30"}
  ]
)`,
  },
];
