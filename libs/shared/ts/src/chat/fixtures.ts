// Shared tool-data fixtures consumed by the web and mobile gallery pages.
// Each entry in `TOOL_FIXTURES` is the exact shape the production chat
// TOOL_RENDERERS receive. Changing a fixture here changes both gallery sides.

import type {
  ArtifactData,
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarFetchData,
  CalendarListFetchData,
  CalendarOptions,
  CodeData,
  ContactData,
  DeepResearchResults,
  EmailComposeData,
  EmailFetchData,
  EmailSentData,
  EmailThreadData,
  GoalDataMessageType,
  GoogleDocsData,
  MCPAppData,
  PeopleSearchData,
  RateLimitData,
  RedditData,
  SearchResults,
  SharedMemoryData,
  TodoProgressData,
  TodoToolData,
  ToolCallEntry,
  ToolName,
  TwitterSearchData,
  TwitterUserData,
  WeatherData,
  WorkflowCreatedData,
  WorkflowDraftData,
} from "./types";

// ---------------------------------------------------------------------------
// Weather
// ---------------------------------------------------------------------------

const weatherFixture: WeatherData = {
  coord: { lon: -122.4194, lat: 37.7749 },
  weather: [
    {
      id: 803,
      main: "Clouds",
      description: "broken clouds",
      icon: "04d",
    },
  ],
  main: {
    temp: 18.5,
    feels_like: 17.8,
    temp_min: 15,
    temp_max: 22,
    pressure: 1015,
    humidity: 72,
  },
  wind: { speed: 4.2, deg: 270 },
  clouds: { all: 75 },
  dt: 1713369600,
  sys: {
    country: "US",
    sunrise: 1713353400,
    sunset: 1713401400,
  },
  timezone: -25200,
  name: "San Francisco",
  location: { city: "San Francisco", country: "US", region: "California" },
  forecast: [
    {
      date: "2026-04-17",
      timestamp: 1713369600,
      temp_min: 13,
      temp_max: 21,
      humidity: 68,
      weather: { main: "Clear", description: "clear sky", icon: "01d" },
    },
    {
      date: "2026-04-18",
      timestamp: 1713456000,
      temp_min: 14,
      temp_max: 23,
      humidity: 65,
      weather: { main: "Clear", description: "sunny", icon: "01d" },
    },
    {
      date: "2026-04-19",
      timestamp: 1713542400,
      temp_min: 15,
      temp_max: 22,
      humidity: 70,
      weather: { main: "Clouds", description: "partly cloudy", icon: "02d" },
    },
    {
      date: "2026-04-20",
      timestamp: 1713628800,
      temp_min: 12,
      temp_max: 18,
      humidity: 78,
      weather: { main: "Rain", description: "light rain", icon: "10d" },
    },
    {
      date: "2026-04-21",
      timestamp: 1713715200,
      temp_min: 11,
      temp_max: 17,
      humidity: 82,
      weather: { main: "Rain", description: "moderate rain", icon: "10d" },
    },
  ],
};

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

const searchResultsFixture: SearchResults = {
  query: "latest react native 0.77 features",
  response_time: 0.82,
  status: "complete",
  web: [
    {
      title: "React Native 0.77 Release Notes",
      url: "https://reactnative.dev/blog/2026/01/15/version-0.77",
      content:
        "React Native 0.77 ships with the new Bridgeless architecture enabled by default and adopts React 19.",
      favicon: "https://reactnative.dev/img/favicon.ico",
    },
    {
      title: "What's new in React Native 0.77 — in depth",
      url: "https://blog.shopify.engineering/react-native-0-77",
      content:
        "Shopify's summary of Bridgeless, the new renderer, and gradle 8 migration.",
      favicon: "https://www.shopify.com/favicon.ico",
    },
    {
      title: "Migrating to RN 0.77 from 0.74",
      url: "https://expo.dev/blog/rn-077-migration",
      content:
        "Expo's migration guide covers native module changes and JSI updates.",
      favicon: "https://expo.dev/favicon.ico",
    },
  ],
  images: [
    "https://reactnative.dev/img/tiny_logo.png",
    "https://expo.dev/static/brand/square-228x228.png",
    "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",
  ],
  news: [
    {
      title: "React Native 0.77 launches with Bridgeless",
      url: "https://news.ycombinator.com/item?id=0001",
      content:
        "HN thread discussing the new architecture and its performance implications.",
      published_date: "2026-01-16",
      source: "Hacker News",
    },
    {
      title: "Meta reports 30% memory improvements in RN 0.77",
      url: "https://theverge.com/2026/1/17/rn-077",
      content:
        "Meta engineering team published benchmark numbers showing memory gains.",
      published_date: "2026-01-17",
      source: "The Verge",
    },
  ],
  answer:
    "React Native 0.77 ships with Bridgeless architecture, React 19 support, and significant memory improvements.",
};

// ---------------------------------------------------------------------------
// Deep research
// ---------------------------------------------------------------------------

const deepResearchFixture: DeepResearchResults = {
  status: "complete",
  metadata: {
    elapsed_time: 34.2,
    total_content_size: 48_200,
    query: "impact of GLP-1 drugs on cardiovascular health",
  },
  sources: [
    {
      url: "https://www.nejm.org/doi/full/10.1056/NEJMoa230105",
      title: "Semaglutide in patients with heart failure",
      snippet:
        "Randomized trial showing 20% reduction in cardiovascular events.",
    },
    {
      url: "https://jamanetwork.com/journals/jama/fullarticle/2817921",
      title: "Long-term effects of GLP-1 on arterial health",
      snippet: "5-year follow-up indicates sustained cardiovascular benefit.",
    },
    {
      url: "https://www.thelancet.com/journals/lancet/article/PIIS0140-6736",
      title: "Meta-analysis of 12 GLP-1 trials",
      snippet:
        "Pooled analysis confirms mortality benefit across 40k patients.",
    },
  ],
  totalSources: 3,
  enhanced_results: [
    {
      title: "Semaglutide in patients with heart failure",
      url: "https://www.nejm.org/doi/full/10.1056/NEJMoa230105",
      full_content:
        "This landmark study demonstrated semaglutide reduced major adverse cardiovascular events by 20% over 3 years...",
    },
  ],
};

// ---------------------------------------------------------------------------
// Email
// ---------------------------------------------------------------------------

const emailFetchFixture: EmailFetchData[] = [
  {
    id: "mail-1",
    thread_id: "thread-1",
    from: "alex@vercel.com",
    from_name: "Alex from Vercel",
    subject: "Your deployment is ready",
    snippet:
      "Production deployment gaia-mobile.vercel.app has completed successfully in 42s. View the build logs…",
    time: "2026-04-17T10:24:00Z",
    date: "Apr 17",
    is_unread: true,
  },
  {
    id: "mail-2",
    thread_id: "thread-2",
    from: "billing@openai.com",
    from_name: "OpenAI Billing",
    subject: "Invoice #A1B2C3 for April 2026",
    snippet:
      "Thanks for your business. Your monthly invoice is now available. Total due: $128.42. Payment method…",
    time: "2026-04-17T08:10:00Z",
    date: "Apr 17",
    is_unread: false,
  },
  {
    id: "mail-3",
    thread_id: "thread-3",
    from: "sarah@linear.app",
    from_name: "Sarah Drasner",
    subject: "Re: mobile chat parity",
    snippet:
      "Looking great! One small nit on the weather card — the temp numeral could be heavier.",
    time: "2026-04-16T21:47:00Z",
    date: "Yesterday",
    is_unread: true,
  },
];

const emailThreadFixture: EmailThreadData = {
  thread_id: "thread-42",
  subject: "Mobile chat gallery review",
  messages_count: 3,
  messages: [
    {
      id: "msg-1",
      from: "sarah@linear.app",
      from_name: "Sarah Drasner",
      subject: "Mobile chat gallery review",
      snippet: "Can we set up a side-by-side comparison page?",
      body: "Hey team — I think we should build a gallery page that renders every tool card with fixture data. That way we can diff web vs mobile in one shot. Thoughts?",
      time: "2026-04-16T18:00:00Z",
      date: "Apr 16",
    },
    {
      id: "msg-2",
      from: "dhruv@heygaia.io",
      from_name: "Dhruv Maradiya",
      subject: "Re: Mobile chat gallery review",
      snippet: "+1, much faster than triggering real tool calls.",
      body: "+1. Much faster than triggering real tool calls every time. I'll spin up `/dev/tool-gallery` on both apps and share fixtures via @gaia/shared.",
      time: "2026-04-16T19:15:00Z",
      date: "Apr 16",
    },
    {
      id: "msg-3",
      from: "sarah@linear.app",
      from_name: "Sarah Drasner",
      subject: "Re: Mobile chat gallery review",
      snippet: "Perfect — let me know when it's up.",
      body: "Perfect — let me know when it's up and I'll do a pass.",
      time: "2026-04-17T09:02:00Z",
      date: "Today",
    },
  ],
};

const emailComposeFixture: EmailComposeData[] = [
  {
    to: ["sarah@linear.app"],
    cc: ["dhruv@heygaia.io"],
    subject: "Mobile chat gallery is ready for review",
    body: "Hi Sarah,\n\nThe tool gallery is live at /dev/tool-gallery on both web and mobile. Same fixture data on both sides — just load and screenshot-diff.\n\nLet me know what jumps out.\n\nDhruv",
    draft_id: "draft-001",
    is_html: false,
  },
];

const emailSentFixture: EmailSentData[] = [
  {
    to: ["sarah@linear.app"],
    subject: "Mobile chat gallery is ready for review",
    body: "Hi Sarah — the gallery is up on both apps. Ping if anything looks off.",
    message_id: "msg-sent-001",
    sent_at: "2026-04-17T10:32:00Z",
    recipients: ["sarah@linear.app", "dhruv@heygaia.io"],
  },
];

const contactsFixture: ContactData[] = [
  {
    name: "Sarah Drasner",
    email: "sarah@linear.app",
    phone: "+1 (555) 010-2200",
    resource_name: "people/c1001",
  },
  {
    name: "Alex Chen",
    email: "alex@vercel.com",
    phone: "+1 (555) 010-2201",
    resource_name: "people/c1002",
  },
  {
    name: "Priya Narayan",
    email: "priya@anthropic.com",
    resource_name: "people/c1003",
  },
];

const peopleSearchFixture: PeopleSearchData[] = [
  {
    name: "Sarah Drasner",
    email: "sarah@linear.app",
    phone: "+1 (555) 010-2200",
    organization: "Linear",
    role: "VP Developer Experience",
    resource_name: "people/p1001",
  },
  {
    name: "Dhruv Maradiya",
    email: "dhruv@heygaia.io",
    organization: "GAIA",
    role: "Founding Engineer",
    resource_name: "people/p1002",
  },
];

// ---------------------------------------------------------------------------
// Calendar
// ---------------------------------------------------------------------------

const calendarOptionsFixture: CalendarOptions[] = [
  {
    summary: "Design review — mobile chat",
    description:
      "Walk through the tool gallery and identify remaining visual gaps vs web.",
    start: "2026-04-18T14:00:00-07:00",
    end: "2026-04-18T14:45:00-07:00",
    calendar_id: "primary",
    calendar_name: "Work",
    background_color: "#00bbff",
    location: "Google Meet",
    is_all_day: false,
    attendees: ["sarah@linear.app", "dhruv@heygaia.io"],
    create_meeting_room: true,
  },
  {
    summary: "Sync with design system team",
    description: "Consolidate shared primitives across web and mobile.",
    start: "2026-04-19T10:00:00-07:00",
    end: "2026-04-19T10:30:00-07:00",
    calendar_id: "primary",
    calendar_name: "Work",
    background_color: "#f59e0b",
    is_all_day: false,
    attendees: ["priya@anthropic.com"],
  },
];

const calendarDeleteFixture: CalendarDeleteOptions[] = [
  {
    action: "delete",
    event_id: "evt-100",
    calendar_id: "primary",
    calendar_name: "Work",
    background_color: "#00bbff",
    summary: "Weekly 1:1",
    description: "Moved to Tuesdays.",
    start: {
      dateTime: "2026-04-18T15:00:00-07:00",
      timeZone: "America/Los_Angeles",
    },
    end: {
      dateTime: "2026-04-18T15:30:00-07:00",
      timeZone: "America/Los_Angeles",
    },
    original_query: "delete my 1:1 on Friday",
  },
];

const calendarEditFixture: CalendarEditOptions[] = [
  {
    action: "edit",
    event_id: "evt-200",
    calendar_id: "primary",
    calendar_name: "Work",
    background_color: "#00bbff",
    original_summary: "Design review",
    original_description: "Review Figma prototypes.",
    original_start: { dateTime: "2026-04-18T14:00:00-07:00" },
    original_end: { dateTime: "2026-04-18T14:30:00-07:00" },
    original_query: "move design review to 4pm",
    summary: "Design review",
    start: "2026-04-18T16:00:00-07:00",
    end: "2026-04-18T16:30:00-07:00",
    is_all_day: false,
    timezone: "America/Los_Angeles",
  },
];

const calendarFetchFixture: CalendarFetchData[] = [
  {
    summary: "Standup",
    start_time: "2026-04-17T09:30:00-07:00",
    end_time: "2026-04-17T09:45:00-07:00",
    calendar_name: "Work",
    background_color: "#00bbff",
  },
  {
    summary: "Focus block — mobile UI",
    start_time: "2026-04-17T10:00:00-07:00",
    end_time: "2026-04-17T12:00:00-07:00",
    calendar_name: "Work",
    background_color: "#10b981",
  },
  {
    summary: "Coffee with Priya",
    start_time: "2026-04-17T15:00:00-07:00",
    end_time: "2026-04-17T15:45:00-07:00",
    calendar_name: "Personal",
    background_color: "#f59e0b",
  },
  {
    summary: "Yoga",
    start_time: "2026-04-18T07:30:00-07:00",
    end_time: "2026-04-18T08:30:00-07:00",
    calendar_name: "Personal",
    background_color: "#a78bfa",
  },
];

const calendarListFixture: CalendarListFetchData[] = [
  {
    id: "primary",
    name: "Work",
    description: "My primary work calendar",
    backgroundColor: "#00bbff",
  },
  {
    id: "cal-personal",
    name: "Personal",
    description: "Personal events and reminders",
    backgroundColor: "#f59e0b",
  },
  {
    id: "cal-family",
    name: "Family",
    description: "Shared with partner and family",
    backgroundColor: "#ef4444",
  },
];

// ---------------------------------------------------------------------------
// Todos & Goals
// ---------------------------------------------------------------------------

const todoFixture: TodoToolData = {
  action: "list",
  message: "Here are your active todos",
  stats: {
    total: 18,
    completed: 7,
    pending: 11,
    overdue: 2,
    today: 4,
    upcoming: 5,
  },
  projects: [
    {
      id: "proj-1",
      name: "Mobile parity",
      color: "#00bbff",
      todo_count: 8,
      completion_percentage: 40,
    },
    {
      id: "proj-2",
      name: "Personal",
      color: "#f59e0b",
      todo_count: 4,
      completion_percentage: 25,
    },
  ],
  todos: [
    {
      id: "todo-1",
      title: "Ship mobile tool gallery",
      description:
        "Gallery page at /dev/tool-gallery rendering every tool card with shared fixtures.",
      completed: false,
      priority: "high",
      labels: ["mobile", "chat"],
      due_date: "2026-04-17",
      project_id: "proj-1",
      subtasks: [
        { id: "s1", title: "Fixtures in @gaia/shared", completed: true },
        { id: "s2", title: "Web gallery page", completed: true },
        { id: "s3", title: "Mobile gallery page", completed: false },
        { id: "s4", title: "Screenshot diff pass", completed: false },
      ],
    },
    {
      id: "todo-2",
      title: "Migrate mobile chat storage to SQLite",
      description:
        "Replace AsyncStorage with op-sqlite + Drizzle. Mirror web's Dexie schema.",
      completed: false,
      priority: "medium",
      labels: ["mobile", "infra"],
      due_date: "2026-04-22",
      project_id: "proj-1",
      subtasks: [],
    },
    {
      id: "todo-3",
      title: "Book flights for team offsite",
      completed: false,
      priority: "low",
      labels: ["travel"],
      project_id: "proj-2",
      subtasks: [],
    },
    {
      id: "todo-4",
      title: "Refill espresso beans",
      completed: true,
      priority: "none",
      labels: [],
      project_id: "proj-2",
      subtasks: [],
    },
  ],
};

const todoProgressFixture: TodoProgressData = {
  plan: {
    source: "agent",
    todos: [
      { id: "1", content: "Read shared chat types", status: "completed" },
      {
        id: "2",
        content: "Build web gallery page",
        status: "in_progress",
      },
      { id: "3", content: "Build mobile gallery page", status: "pending" },
      { id: "4", content: "Screenshot diff pass", status: "pending" },
    ],
  },
};

const goalFixture: GoalDataMessageType = {
  action: "list",
  message: "You have 2 active goals",
  stats: {
    total_goals: 2,
    goals_with_roadmaps: 2,
    total_tasks: 18,
    completed_tasks: 7,
    overall_completion_rate: 38.8,
    active_goals: [
      { id: "goal-1", title: "Ship mobile parity", progress: 62 },
      { id: "goal-2", title: "Run a sub-2hr half-marathon", progress: 28 },
    ],
    active_goals_count: 2,
  },
  goals: [
    {
      id: "goal-1",
      title: "Ship mobile parity",
      description: "Close the visual gap between web and mobile chat.",
      progress: 62,
      created_at: "2026-03-01T00:00:00Z",
    },
    {
      id: "goal-2",
      title: "Run a sub-2hr half-marathon",
      description: "Train progressively to hit the target pace.",
      progress: 28,
      created_at: "2026-02-10T00:00:00Z",
    },
  ],
};

// ---------------------------------------------------------------------------
// Documents / Code / Artifacts
// ---------------------------------------------------------------------------

const googleDocsFixture: GoogleDocsData = {
  action: "create",
  message: "Created a new Google Doc: Mobile Chat Parity Plan",
  document: {
    id: "1abcXYZ",
    title: "Mobile Chat Parity Plan",
    url: "https://docs.google.com/document/d/1abcXYZ/edit",
    created_time: "2026-04-17T10:00:00Z",
    modified_time: "2026-04-17T10:05:00Z",
    type: "document",
  },
};

const codeFixture: CodeData = {
  language: "python",
  status: "completed",
  code: `import numpy as np
import matplotlib.pyplot as plt

data = np.random.normal(0, 1, 1000)
plt.hist(data, bins=40, color="#00bbff")
plt.title("Sample distribution")
plt.show()

print(f"mean={data.mean():.3f} std={data.std():.3f}")`,
  output: {
    stdout: "mean=0.012 std=1.003\n",
    stderr: "",
    results: [],
    error: null,
  },
  charts: [
    {
      id: "chart-1",
      url: "https://example.com/chart.png",
      text: "Sample distribution",
      type: "bar",
      title: "Sample distribution",
      chart_data: {
        type: "bar",
        title: "Sample distribution",
        x_label: "Bucket",
        y_label: "Count",
        elements: [
          { label: "-3σ", value: 4, group: "dist" },
          { label: "-2σ", value: 32, group: "dist" },
          { label: "-1σ", value: 178, group: "dist" },
          { label: "0", value: 402, group: "dist" },
          { label: "1σ", value: 254, group: "dist" },
          { label: "2σ", value: 110, group: "dist" },
          { label: "3σ", value: 20, group: "dist" },
        ],
      },
    },
  ],
};

const artifactFixture: ArtifactData[] = [
  {
    path: "/artifacts/gaia/mobile-parity-plan.pdf",
    filename: "mobile-parity-plan.pdf",
    content_type: "application/pdf",
    size_bytes: 382_104,
  },
  {
    path: "/artifacts/gaia/analytics.csv",
    filename: "analytics.csv",
    content_type: "text/csv",
    size_bytes: 18_422,
  },
];

// ---------------------------------------------------------------------------
// Twitter
// ---------------------------------------------------------------------------

const twitterUser: TwitterUserData = {
  id: "u1",
  username: "dan_abramov",
  name: "Dan Abramov",
  description: "Working on React.",
  verified: true,
  profile_image_url: "https://pbs.twimg.com/profile_images/default.jpg",
  public_metrics: {
    followers_count: 445_000,
    following_count: 512,
    tweet_count: 18_220,
    listed_count: 4_200,
  },
  location: "London",
  url: "https://overreacted.io",
};

const twitterSearchFixture: TwitterSearchData = {
  result_count: 3,
  tweets: [
    {
      id: "t1",
      text: "RN 0.77 Bridgeless is genuinely wild — we dropped ~30% JS frame time in our iMessage clone.",
      created_at: "2026-04-17T09:12:00Z",
      author: twitterUser,
      public_metrics: {
        like_count: 1_240,
        retweet_count: 88,
        reply_count: 42,
        quote_count: 9,
      },
    },
    {
      id: "t2",
      text: "Shoutout to the GAIA team — the mobile chat rewrite is pristine.",
      created_at: "2026-04-17T08:02:00Z",
      author: {
        ...twitterUser,
        id: "u2",
        username: "satyanadella",
        name: "Satya Nadella",
        description: "Chairman and CEO at Microsoft.",
      },
      public_metrics: {
        like_count: 9_100,
        retweet_count: 420,
        reply_count: 188,
      },
    },
  ],
};

const twitterUsersFixture: TwitterUserData[] = [twitterUser];

// ---------------------------------------------------------------------------
// Reddit
// ---------------------------------------------------------------------------

const redditFixture: RedditData = {
  type: "search",
  posts: [
    {
      id: "p1",
      title:
        "What's the best way to structure a React Native monorepo in 2026?",
      author: "u/dev_curious",
      subreddit: "reactnative",
      score: 412,
      num_comments: 88,
      created_utc: 1713369600,
      permalink: "/r/reactnative/comments/p1",
      selftext:
        "We're rebuilding our app and considering Nx vs pnpm workspaces. What's working for you?",
    },
    {
      id: "p2",
      title: "Anyone tried op-sqlite + Drizzle yet?",
      author: "u/ts_fan",
      subreddit: "reactnative",
      score: 188,
      num_comments: 34,
      created_utc: 1713283200,
      permalink: "/r/reactnative/comments/p2",
    },
  ],
};

// ---------------------------------------------------------------------------
// Integrations
// ---------------------------------------------------------------------------

const integrationConnectionFixture: Record<string, unknown> = {
  integration_id: "gcal",
  integration_name: "Google Calendar",
  message: "Connect Google Calendar to let GAIA schedule events for you.",
  icon_url:
    "https://www.google.com/calendar/images/ext/calendar_ext_favicon.png",
  connect_url: "/integrations/connect/gcal",
};

const integrationListFixture: Record<string, unknown> = {
  hasSuggestions: true,
  message: "Based on what you use, these would help GAIA the most.",
  suggested: [
    {
      id: "gmail",
      name: "Gmail",
      description: "Read and send email on your behalf.",
      icon_url:
        "https://ssl.gstatic.com/images/branding/product/1x/gmail_2020q4_48dp.png",
    },
    {
      id: "gcal",
      name: "Google Calendar",
      description: "Create, edit, and query calendar events.",
      icon_url:
        "https://www.google.com/calendar/images/ext/calendar_ext_favicon.png",
    },
    {
      id: "linear",
      name: "Linear",
      description: "Create issues and track work.",
      icon_url: "https://linear.app/favicon.ico",
    },
    {
      id: "notion",
      name: "Notion",
      description: "Read and update your Notion workspace.",
      icon_url: "https://www.notion.so/images/favicon.ico",
    },
  ],
};

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------

const workflowDraftFixture: WorkflowDraftData = {
  suggested_title: "Weekday morning brief",
  suggested_description:
    "Every weekday at 8am, summarize today's calendar, top emails, and overdue todos.",
  prompt:
    "Give me a morning brief: today's calendar, the 3 most important unread emails, and any overdue tasks.",
  trigger_type: "scheduled",
  cron_expression: "0 8 * * 1-5",
};

const workflowCreatedFixture: WorkflowCreatedData = {
  id: "wf-001",
  title: "Weekday morning brief",
  description: "Every weekday at 8am, summarize today's calendar and tasks.",
  trigger_config: {
    type: "scheduled",
    cron_expression: "0 8 * * 1-5",
    enabled: true,
  },
  activated: true,
};

// ---------------------------------------------------------------------------
// Misc
// ---------------------------------------------------------------------------

const supportTicketFixture: Record<string, unknown>[] = [
  {
    id: "tkt-501",
    title: "Can't connect Notion integration",
    type: "bug",
    status: "open",
    priority: "high",
    description:
      "OAuth flow returns a 500 after clicking Authorize. Repro on iOS + Android.",
    created_at: "2026-04-16T14:00:00Z",
  },
];

const notificationFixture: Record<string, unknown> = {
  notifications: [
    {
      id: "n1",
      title: "Deployment succeeded",
      body: "gaia-mobile build 1042 is live.",
      type: "deploy",
      created_at: "2026-04-17T10:05:00Z",
    },
    {
      id: "n2",
      title: "New message from Sarah",
      body: "Looking great! One small nit on the weather card…",
      type: "email",
      created_at: "2026-04-17T09:47:00Z",
    },
  ],
};

const rateLimitFixture: RateLimitData = {
  feature: "Deep research",
  plan_required: "Pro",
  reset_time: "2026-04-17T18:00:00Z",
};

const memoryFixture: SharedMemoryData = {
  operation: "search",
  status: "ok",
  count: 2,
  results: [
    {
      id: "mem-1",
      content: "Dhruv's preferred chart palette starts with #00bbff.",
      relevance_score: 0.91,
    },
    {
      id: "mem-2",
      content: "Mobile chat parity is the current north-star project.",
      relevance_score: 0.82,
    },
  ],
};

const mcpAppFixture: MCPAppData = {
  tool_call_id: "mcp-1",
  tool_name: "stripe.get_subscription",
  server_url: "https://mcp.stripe.com",
  resource_uri: "stripe://subscription/sub_123",
  html_content:
    '<div style="padding:16px;color:#e5e7eb;background:#18181b;border-radius:12px"><strong>Active subscription</strong><p>$29/mo · renews Apr 28</p></div>',
};

const toolCallsFixture: ToolCallEntry[] = [
  {
    tool_name: "calendar.fetch_events",
    tool_category: "calendar",
    message: "Fetched 4 events for today",
    integration_name: "Google Calendar",
  },
  {
    tool_name: "mail.get_inbox",
    tool_category: "email",
    message: "Pulled latest 3 unread emails",
    integration_name: "Gmail",
  },
];

const connectionStatusFixture: Record<string, unknown> = {
  integrations: [
    { id: "gmail", name: "Gmail", connected: true },
    { id: "gcal", name: "Google Calendar", connected: true },
    { id: "notion", name: "Notion", connected: false },
    { id: "linear", name: "Linear", connected: true },
  ],
};

const chartDataFixture: Record<string, unknown>[] = [
  {
    type: "bar",
    title: "Weekly commits",
    x_label: "Day",
    y_label: "Commits",
    elements: [
      { label: "Mon", value: 12, group: "a" },
      { label: "Tue", value: 18, group: "a" },
      { label: "Wed", value: 9, group: "a" },
      { label: "Thu", value: 22, group: "a" },
      { label: "Fri", value: 15, group: "a" },
    ],
  },
];

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

/**
 * Display metadata for a fixture — used by gallery pages to render section
 * headers alongside the actual tool card.
 */
export interface ToolFixture<T = unknown> {
  toolName: ToolName;
  label: string;
  description: string;
  data: T;
}

export const TOOL_FIXTURES: readonly ToolFixture[] = [
  {
    toolName: "weather_data",
    label: "Weather",
    description:
      "Rich forecast with hero temp, stats, sunrise/sunset, and 5-day outlook.",
    data: weatherFixture,
  },
  {
    toolName: "search_results",
    label: "Search",
    description: "Web + images + news tabs with query summary.",
    data: searchResultsFixture,
  },
  {
    toolName: "deep_research_results",
    label: "Deep research",
    description: "Multi-source research summary with citations.",
    data: deepResearchFixture,
  },
  {
    toolName: "email_fetch_data",
    label: "Email inbox",
    description: "List of fetched emails with unread indicators.",
    data: emailFetchFixture,
  },
  {
    toolName: "email_thread_data",
    label: "Email thread",
    description: "Expandable thread with multiple messages.",
    data: emailThreadFixture,
  },
  {
    toolName: "email_compose_data",
    label: "Email compose",
    description: "Draft preview before sending.",
    data: emailComposeFixture,
  },
  {
    toolName: "email_sent_data",
    label: "Email sent",
    description: "Confirmation after a successful send.",
    data: emailSentFixture,
  },
  {
    toolName: "contacts_data",
    label: "Contacts",
    description: "Address-book lookup result.",
    data: contactsFixture,
  },
  {
    toolName: "people_search_data",
    label: "People search",
    description: "Enriched person profiles with org and role.",
    data: peopleSearchFixture,
  },
  {
    toolName: "calendar_options",
    label: "Calendar create",
    description: "Proposed calendar event(s) awaiting confirmation.",
    data: calendarOptionsFixture,
  },
  {
    toolName: "calendar_delete_options",
    label: "Calendar delete",
    description: "Preview of event(s) about to be deleted.",
    data: calendarDeleteFixture,
  },
  {
    toolName: "calendar_edit_options",
    label: "Calendar edit",
    description: "Before/after comparison for a calendar edit.",
    data: calendarEditFixture,
  },
  {
    toolName: "calendar_fetch_data",
    label: "Calendar fetch",
    description: "Events grouped by date.",
    data: calendarFetchFixture,
  },
  {
    toolName: "calendar_list_fetch_data",
    label: "Calendar list",
    description: "User's calendars with colors.",
    data: calendarListFixture,
  },
  {
    toolName: "todo_data",
    label: "Todos",
    description: "Todo list with priorities, projects, stats, and subtasks.",
    data: todoFixture,
  },
  {
    toolName: "todo_progress",
    label: "Todo progress (agent plan)",
    description: "Live agent task plan with pending / in-progress / complete.",
    data: todoProgressFixture,
  },
  {
    toolName: "goal_data",
    label: "Goals",
    description: "Long-running goals with progress and stats.",
    data: goalFixture,
  },
  {
    toolName: "google_docs_data",
    label: "Google Docs",
    description: "Newly created or referenced Google Doc.",
    data: googleDocsFixture,
  },
  {
    toolName: "code_data",
    label: "Code execution",
    description: "Code, stdout, and generated chart artifact.",
    data: codeFixture,
  },
  {
    toolName: "artifact_data",
    label: "Artifacts",
    description: "Generated files available for download.",
    data: artifactFixture,
  },
  {
    toolName: "twitter_search_data",
    label: "Twitter search",
    description: "Search results as tweet cards.",
    data: twitterSearchFixture,
  },
  {
    toolName: "twitter_user_data",
    label: "Twitter users",
    description: "User profile cards with metrics.",
    data: twitterUsersFixture,
  },
  {
    toolName: "reddit_data",
    label: "Reddit search",
    description: "Reddit post results grouped by type.",
    data: redditFixture,
  },
  {
    toolName: "integration_connection_required",
    label: "Integration prompt",
    description: "Prompt to connect a missing integration.",
    data: integrationConnectionFixture,
  },
  {
    toolName: "integration_list_data",
    label: "Integration suggestions",
    description: "Suggested integrations based on usage.",
    data: integrationListFixture,
  },
  {
    toolName: "connection_status_data",
    label: "Connection status",
    description: "Summary of connected / disconnected integrations.",
    data: connectionStatusFixture,
  },
  {
    toolName: "workflow_draft",
    label: "Workflow draft",
    description: "Proposed workflow awaiting user confirmation.",
    data: workflowDraftFixture,
  },
  {
    toolName: "workflow_created",
    label: "Workflow created",
    description: "Confirmation that a workflow was saved.",
    data: workflowCreatedFixture,
  },
  {
    toolName: "support_ticket_data",
    label: "Support ticket",
    description: "Created or updated support ticket.",
    data: supportTicketFixture,
  },
  {
    toolName: "notification_data",
    label: "Notifications",
    description: "List of recent user notifications.",
    data: notificationFixture,
  },
  {
    toolName: "rate_limit_data",
    label: "Rate limit",
    description: "Feature-gated rate-limit error with reset time.",
    data: rateLimitFixture,
  },
  {
    toolName: "memory_data",
    label: "Memory",
    description: "Semantic memory lookup results.",
    data: memoryFixture,
  },
  {
    toolName: "mcp_app",
    label: "MCP app",
    description: "Embedded HTML UI from an MCP server.",
    data: mcpAppFixture,
  },
  {
    toolName: "tool_calls_data",
    label: "Tool calls log",
    description: "Compact log of which tools the agent called.",
    data: toolCallsFixture,
  },
  {
    toolName: "chart_data",
    label: "Chart",
    description: "Standalone chart data.",
    data: chartDataFixture,
  },
];

export function getFixture<K extends ToolName>(
  toolName: K,
): ToolFixture | undefined {
  return TOOL_FIXTURES.find((f) => f.toolName === toolName);
}
