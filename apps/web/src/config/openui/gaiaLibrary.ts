import { createLibrary, defineComponent } from "@openuidev/react-lang";
import React from "react";
import { z } from "zod";
import CalendarListCard from "@/features/calendar/components/CalendarListCard";
import CalendarListFetchCard from "@/features/calendar/components/CalendarListFetchCard";
import EmailListCard from "@/features/mail/components/EmailListCard";
import ContactListCard from "@/features/mail/components/ContactListCard";
import PeopleSearchCard from "@/features/mail/components/PeopleSearchCard";
import { IntegrationListSection } from "@/features/integrations/components/IntegrationListSection";
import EmailThreadCard from "@/features/chat/components/bubbles/bot/EmailThreadCard";
import TodoSection from "@/features/chat/components/bubbles/bot/TodoSection";
import GoalSection from "@/features/chat/components/bubbles/bot/goals/GoalSection";
import NotificationListSection from "@/features/chat/components/bubbles/bot/NotificationListSection";
import DocumentSection from "@/features/chat/components/bubbles/bot/DocumentSection";
import GoogleDocsSection from "@/features/chat/components/bubbles/bot/GoogleDocsSection";
import DeepResearchResultsTabs from "@/features/chat/components/bubbles/bot/DeepResearchResultsTabs";
import TwitterSearchSection from "@/features/chat/components/bubbles/bot/TwitterSearchSection";
import SearchResultsTabs from "@/features/chat/components/bubbles/bot/SearchResultsTabs";
import { WeatherCard } from "@/features/weather/components/WeatherCard";
import type { CalendarFetchData, CalendarListFetchData } from "@/types/features/calendarTypes";
import type { SearchResults, WeatherData, DeepResearchResults, DocumentData, GoalDataMessageType, GoogleDocsData } from "@/types/features/convoTypes";
import type { EmailFetchData, EmailThreadData, ContactData, PeopleSearchData } from "@/types/features/mailTypes";
import type { TodoToolData } from "@/types/features/todoToolTypes";
import type { NotificationRecord } from "@/types/features/notificationTypes";
import type { SuggestedIntegration } from "@/features/integrations/types";
import type { TwitterSearchData } from "@/types/features/twitterTypes";

// --- Zod Schemas ---

const weatherConditionSchema = z.object({
  id: z.number(),
  main: z.string(),
  description: z.string(),
  icon: z.string(),
});

const forecastDaySchema = z.object({
  date: z.string(),
  timestamp: z.number(),
  temp_min: z.number(),
  temp_max: z.number(),
  humidity: z.number(),
  weather: z.object({
    main: z.string(),
    description: z.string(),
    icon: z.string(),
  }),
});

const weatherDataSchema = z.object({
  coord: z.object({ lon: z.number(), lat: z.number() }),
  weather: z.array(weatherConditionSchema),
  base: z.string().optional(),
  main: z.object({
    temp: z.number(),
    feels_like: z.number(),
    temp_min: z.number(),
    temp_max: z.number(),
    pressure: z.number(),
    humidity: z.number(),
    sea_level: z.number().optional(),
    grnd_level: z.number().optional(),
  }),
  visibility: z.number().optional(),
  wind: z.object({
    speed: z.number(),
    deg: z.number(),
    gust: z.number().optional(),
  }),
  clouds: z.object({ all: z.number() }).optional(),
  dt: z.number(),
  sys: z.object({
    country: z.string(),
    sunrise: z.number(),
    sunset: z.number(),
  }),
  timezone: z.number(),
  id: z.number().optional(),
  name: z.string(),
  cod: z.number().optional(),
  location: z.object({
    city: z.string(),
    country: z.string().nullable(),
    region: z.string().nullable(),
  }),
  forecast: z.array(forecastDaySchema).optional(),
});

const calendarEventSchema = z.object({
  summary: z.string(),
  start_time: z.string(),
  end_time: z.string(),
  calendar_name: z.string(),
  background_color: z.string(),
});

const calendarListSchema = z.object({
  events: z.array(calendarEventSchema),
});

const webResultSchema = z.object({
  title: z.string(),
  url: z.string(),
  content: z.string(),
  score: z.number(),
  raw_content: z.string().optional(),
  favicon: z.string().optional(),
});

const newsResultSchema = z.object({
  title: z.string(),
  url: z.string(),
  content: z.string(),
  score: z.number(),
  raw_content: z.string().optional(),
  favicon: z.string().optional(),
});

const searchResultsSchema = z.object({
  web: z.array(webResultSchema).optional(),
  images: z.array(z.string()).optional(),
  news: z.array(newsResultSchema).optional(),
  answer: z.string().optional(),
  query: z.string().optional(),
  response_time: z.number().optional(),
  request_id: z.string().optional(),
});

// EmailListCard schema
const emailFetchDataSchema = z.object({
  from: z.string(),
  subject: z.string(),
  time: z.string(),
  thread_id: z.string().optional(),
  id: z.string(),
});

const emailListSchema = z.object({
  emails: z.array(emailFetchDataSchema),
});

// EmailThreadCard schema
const emailThreadMessageSchema = z.object({
  id: z.string(),
  from: z.string(),
  subject: z.string(),
  time: z.string(),
  snippet: z.string(),
  body: z.string(),
  content: z.object({ text: z.string(), html: z.string() }).optional(),
});

const emailThreadDataSchema = z.object({
  thread_id: z.string(),
  messages: z.array(emailThreadMessageSchema),
  messages_count: z.number(),
});

// ContactListCard schema
const contactDataSchema = z.object({
  name: z.string(),
  email: z.string(),
  phone: z.string().optional(),
  resource_name: z.string(),
});

const contactListSchema = z.object({
  contacts: z.array(contactDataSchema),
});

// PeopleSearchCard schema
const peopleSearchDataSchema = z.object({
  name: z.string(),
  email: z.string(),
  phone: z.string().optional(),
  resource_name: z.string(),
});

const peopleSearchSchema = z.object({
  people: z.array(peopleSearchDataSchema),
});

// TodoListCard schema
const todoSubtaskSchema = z.object({
  id: z.string(),
  title: z.string(),
  completed: z.boolean(),
});

const todoProjectSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().optional(),
  color: z.string().optional(),
  is_default: z.boolean().optional(),
  todo_count: z.number().optional(),
  completion_percentage: z.number().optional(),
});

const todoItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().optional(),
  completed: z.boolean(),
  priority: z.string(),
  labels: z.array(z.string()),
  due_date: z.string().optional(),
  due_date_timezone: z.string().optional(),
  project_id: z.string().optional(),
  project: todoProjectSchema.optional(),
  subtasks: z.array(todoSubtaskSchema),
  created_at: z.string(),
  updated_at: z.string(),
  workflow: z.unknown().optional(),
});

const todoStatsSchema = z.object({
  total: z.number(),
  completed: z.number(),
  pending: z.number(),
  overdue: z.number(),
  today: z.number(),
  upcoming: z.number(),
});

const todoListSchema = z.object({
  todos: z.array(todoItemSchema).optional(),
  projects: z.array(todoProjectSchema).optional(),
  stats: todoStatsSchema.optional(),
  action: z.string().optional(),
  message: z.string().optional(),
});

// GoalCard schema
const goalNodeSchema = z.object({
  id: z.string(),
  data: z.object({
    title: z.string().optional(),
    label: z.string().optional(),
    isComplete: z.boolean().optional(),
    type: z.string().optional(),
    subtask_id: z.string().optional(),
  }),
});

const goalEdgeSchema = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
});

const goalItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().optional(),
  progress: z.number().optional(),
  roadmap: z
    .object({
      nodes: z.array(goalNodeSchema),
      edges: z.array(goalEdgeSchema),
    })
    .optional(),
  created_at: z.string().optional(),
  todo_project_id: z.string().optional(),
  todo_id: z.string().optional(),
});

const goalStatsSchema = z.object({
  total_goals: z.number(),
  goals_with_roadmaps: z.number(),
  total_tasks: z.number(),
  completed_tasks: z.number(),
  overall_completion_rate: z.number(),
  active_goals: z.array(
    z.object({
      id: z.string(),
      title: z.string(),
      progress: z.number(),
    }),
  ),
  active_goals_count: z.number(),
});

const goalCardSchema = z.object({
  goals: z.array(goalItemSchema).optional(),
  action: z.string().optional(),
  message: z.string().optional(),
  goal_id: z.string().optional(),
  deleted_goal_id: z.string().optional(),
  stats: goalStatsSchema.optional(),
  error: z.string().optional(),
});

// NotificationCard schema
const notificationContentSchema = z.object({
  title: z.string(),
  body: z.string(),
  actions: z.array(z.unknown()).optional(),
  rich_content: z.unknown().optional(),
});

const channelDeliveryStatusSchema = z.object({
  channel_type: z.string(),
  status: z.string(),
  delivered_at: z.string().optional(),
  error_message: z.string().optional(),
  retry_count: z.number().optional(),
});

const notificationRecordSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  status: z.string(),
  type: z.string(),
  created_at: z.string(),
  delivered_at: z.string().optional(),
  read_at: z.string().optional(),
  source: z.string(),
  content: notificationContentSchema,
  metadata: z.record(z.string(), z.unknown()).optional(),
  channels: z.array(channelDeliveryStatusSchema),
});

const notificationCardSchema = z.object({
  notifications: z.array(notificationRecordSchema),
  title: z.string().optional(),
});

// IntegrationListCard schema
const suggestedIntegrationSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  category: z.string(),
  iconUrl: z.string().nullable().optional(),
  authType: z.string().nullable().optional(),
  relevanceScore: z.number(),
  slug: z.string(),
});

const integrationListCardSchema = z.object({
  suggestedIntegrations: z.array(suggestedIntegrationSchema).optional(),
});

// DocumentCard schema
const documentCardSchema = z.object({
  document_data: z.object({
    filename: z.string(),
    url: z.string(),
    is_plain_text: z.boolean(),
    title: z.string(),
    metadata: z.record(z.string(), z.unknown()),
  }),
});

// GoogleDocsCard schema
const googleDocsCardSchema = z.object({
  google_docs_data: z.object({
    document: z.object({
      id: z.string(),
      title: z.string(),
      url: z.string(),
      created_time: z.string(),
      modified_time: z.string(),
      type: z.string(),
    }),
    query: z.string().nullable().optional(),
    action: z.string(),
    message: z.string(),
    type: z.string(),
  }),
});

// DeepResearchCard schema
const enhancedWebResultSchema = z.object({
  title: z.string(),
  url: z.string(),
  content: z.string(),
  score: z.number(),
  raw_content: z.string().optional(),
  favicon: z.string().optional(),
  full_content: z.string().optional(),
  screenshot_url: z.string().optional(),
});

const deepResearchCardSchema = z.object({
  deep_research_results: z.object({
    original_search: searchResultsSchema.optional(),
    enhanced_results: z.array(enhancedWebResultSchema).optional(),
    screenshots_taken: z.boolean().optional(),
    metadata: z
      .object({
        total_content_size: z.number().optional(),
        elapsed_time: z.number().optional(),
        query: z.string().optional(),
      })
      .optional(),
  }),
});

// CalendarListFetchCard schema
const calendarListFetchItemSchema = z.object({
  name: z.string(),
  id: z.string(),
  description: z.string(),
  backgroundColor: z.string().optional(),
});

const calendarListFetchCardSchema = z.object({
  calendars: z.array(calendarListFetchItemSchema),
});

// TwitterSearchCard schema
const twitterUserDataSchema = z.object({
  id: z.string(),
  username: z.string(),
  name: z.string(),
  description: z.string().optional(),
  profile_image_url: z.string().optional(),
  verified: z.boolean().optional(),
  public_metrics: z
    .object({
      followers_count: z.number().optional(),
      following_count: z.number().optional(),
      tweet_count: z.number().optional(),
      listed_count: z.number().optional(),
    })
    .optional(),
  created_at: z.string().optional(),
  location: z.string().optional(),
  url: z.string().optional(),
});

const twitterTweetDataSchema = z.object({
  id: z.string(),
  text: z.string(),
  created_at: z.string().optional(),
  author: twitterUserDataSchema,
  public_metrics: z
    .object({
      retweet_count: z.number().optional(),
      reply_count: z.number().optional(),
      like_count: z.number().optional(),
      quote_count: z.number().optional(),
      bookmark_count: z.number().optional(),
      impression_count: z.number().optional(),
    })
    .optional(),
  conversation_id: z.string().optional(),
});

const twitterSearchCardSchema = z.object({
  twitter_search_data: z.object({
    tweets: z.array(twitterTweetDataSchema),
    result_count: z.number().optional(),
    next_token: z.string().optional(),
  }),
});

// --- Component Definitions ---

const WeatherCardComponent = defineComponent({
  name: "WeatherCard",
  description:
    "Displays current weather conditions with temperature, forecast, and details for a location.",
  props: weatherDataSchema,
  component: ({ props }) =>
    React.createElement(WeatherCard, {
      weatherData: props as unknown as WeatherData,
    }),
});

const CalendarListCardComponent = defineComponent({
  name: "CalendarListCard",
  description:
    "Displays a list of calendar events with times, names, and calendar colors.",
  props: calendarListSchema,
  component: ({ props }) => {
    const { events } = props as unknown as { events: CalendarFetchData[] };
    return React.createElement(CalendarListCard, { events });
  },
});

const SearchResultsTabsComponent = defineComponent({
  name: "SearchResultsTabs",
  description:
    "Displays search results in tabs: web results, image gallery, and news articles.",
  props: searchResultsSchema,
  component: ({ props }) =>
    React.createElement(SearchResultsTabs, {
      search_results: props as unknown as SearchResults,
    }),
});

const EmailListCardComponent = defineComponent({
  name: "EmailListCard",
  description:
    "Displays a list of emails with sender, subject, and time. Clicking an email opens it in chat.",
  props: emailListSchema,
  component: ({ props }) => {
    const { emails } = props as unknown as { emails: EmailFetchData[] };
    return React.createElement(EmailListCard, { emails });
  },
});

const EmailThreadCardComponent = defineComponent({
  name: "EmailThreadCard",
  description:
    "Displays a full email thread with all messages expanded in an accordion.",
  props: emailThreadDataSchema,
  component: ({ props }) =>
    React.createElement(EmailThreadCard, {
      emailThreadData: props as unknown as EmailThreadData,
    }),
});

const ContactListCardComponent = defineComponent({
  name: "ContactListCard",
  description:
    "Displays a list of contacts with name, email, and phone number.",
  props: contactListSchema,
  component: ({ props }) => {
    const { contacts } = props as unknown as { contacts: ContactData[] };
    return React.createElement(ContactListCard, { contacts });
  },
});

const PeopleSearchCardComponent = defineComponent({
  name: "PeopleSearchCard",
  description:
    "Displays people search results with name, email, and phone number.",
  props: peopleSearchSchema,
  component: ({ props }) => {
    const { people } = props as unknown as { people: PeopleSearchData[] };
    return React.createElement(PeopleSearchCard, { people });
  },
});

const TodoListCardComponent = defineComponent({
  name: "TodoListCard",
  description:
    "Displays todos, projects, and task statistics in an interactive card.",
  props: todoListSchema,
  component: ({ props }) => {
    const data = props as unknown as TodoToolData;
    return React.createElement(TodoSection, {
      todos: data.todos,
      projects: data.projects,
      stats: data.stats,
      action: data.action,
      message: data.message,
    });
  },
});

const GoalCardComponent = defineComponent({
  name: "GoalCard",
  description:
    "Displays goals with progress, roadmap nodes, and statistics.",
  props: goalCardSchema,
  component: ({ props }) => {
    const data = props as unknown as GoalDataMessageType;
    return React.createElement(GoalSection, {
      goals: data.goals as unknown as Parameters<typeof GoalSection>[0]["goals"],
      stats: data.stats as unknown as Parameters<typeof GoalSection>[0]["stats"],
      action: data.action as unknown as Parameters<typeof GoalSection>[0]["action"],
      message: data.message,
      goal_id: data.goal_id,
      deleted_goal_id: data.deleted_goal_id,
      error: data.error,
    });
  },
});

const NotificationCardComponent = defineComponent({
  name: "NotificationCard",
  description:
    "Displays a list of notifications with type, status, and actions.",
  props: notificationCardSchema,
  component: ({ props }) => {
    const { notifications, title } = props as unknown as {
      notifications: NotificationRecord[];
      title?: string;
    };
    return React.createElement(NotificationListSection, {
      notifications,
      title,
    });
  },
});

const IntegrationListCardComponent = defineComponent({
  name: "IntegrationListCard",
  description:
    "Displays available and suggested integrations with connect actions.",
  props: integrationListCardSchema,
  component: ({ props }) => {
    const { suggestedIntegrations } = props as unknown as {
      suggestedIntegrations?: SuggestedIntegration[];
    };
    return React.createElement(IntegrationListSection, {
      suggestedIntegrations,
    });
  },
});

const DocumentCardComponent = defineComponent({
  name: "DocumentCard",
  description:
    "Displays a document card with file info and a download button.",
  props: documentCardSchema,
  component: ({ props }) =>
    React.createElement(DocumentSection, {
      document_data: (props as unknown as { document_data: DocumentData })
        .document_data,
    }),
});

const GoogleDocsCardComponent = defineComponent({
  name: "GoogleDocsCard",
  description:
    "Displays a Google Docs document with title, action, and a link to open it.",
  props: googleDocsCardSchema,
  component: ({ props }) =>
    React.createElement(GoogleDocsSection, {
      google_docs_data: (
        props as unknown as { google_docs_data: GoogleDocsData }
      ).google_docs_data,
    }),
});

const DeepResearchCardComponent = defineComponent({
  name: "DeepResearchCard",
  description:
    "Displays deep research results with enhanced web results, original search, and metadata tabs.",
  props: deepResearchCardSchema,
  component: ({ props }) =>
    React.createElement(DeepResearchResultsTabs, {
      deep_research_results: (
        props as unknown as { deep_research_results: DeepResearchResults }
      ).deep_research_results,
    }),
});

const CalendarListFetchCardComponent = defineComponent({
  name: "CalendarListFetchCard",
  description:
    "Displays a list of fetched calendars with names, descriptions, and color indicators.",
  props: calendarListFetchCardSchema,
  component: ({ props }) => {
    const { calendars } = props as unknown as {
      calendars: CalendarListFetchData[];
    };
    return React.createElement(CalendarListFetchCard, { calendars });
  },
});

const TwitterSearchCardComponent = defineComponent({
  name: "TwitterSearchCard",
  description:
    "Displays Twitter search results as tweet cards with author info and engagement metrics.",
  props: twitterSearchCardSchema,
  component: ({ props }) =>
    React.createElement(TwitterSearchSection, {
      twitter_search_data: (
        props as unknown as { twitter_search_data: TwitterSearchData }
      ).twitter_search_data,
    }),
});

// --- Library ---

export const gaiaLibrary = createLibrary({
  components: [
    WeatherCardComponent,
    CalendarListCardComponent,
    SearchResultsTabsComponent,
    EmailListCardComponent,
    EmailThreadCardComponent,
    ContactListCardComponent,
    PeopleSearchCardComponent,
    TodoListCardComponent,
    GoalCardComponent,
    NotificationCardComponent,
    IntegrationListCardComponent,
    DocumentCardComponent,
    GoogleDocsCardComponent,
    DeepResearchCardComponent,
    CalendarListFetchCardComponent,
    TwitterSearchCardComponent,
  ],
  componentGroups: [
    {
      name: "Data Display",
      components: ["WeatherCard", "CalendarListCard", "SearchResultsTabs"],
      notes: [
        "Use these components to present tool results visually.",
        "Always pass the full data object from the tool result.",
        "The agent should still write natural conversational text before/after the component.",
      ],
    },
    {
      name: "Communication",
      components: [
        "EmailListCard",
        "EmailThreadCard",
        "ContactListCard",
        "PeopleSearchCard",
      ],
      notes: [
        "Use EmailListCard to show a list of emails from fetch results.",
        "Use EmailThreadCard to show a full email thread.",
        "Use ContactListCard to show contacts from address book lookups.",
        "Use PeopleSearchCard to show people search results.",
      ],
    },
    {
      name: "Productivity",
      components: ["TodoListCard", "GoalCard", "NotificationCard"],
      notes: [
        "Use TodoListCard to display tasks, projects, or statistics.",
        "Use GoalCard to display goals with progress and roadmap data.",
        "Use NotificationCard to display notifications with actions.",
      ],
    },
    {
      name: "Integrations & Documents",
      components: ["IntegrationListCard", "DocumentCard", "GoogleDocsCard"],
      notes: [
        "Use IntegrationListCard to display available and suggested integrations.",
        "Use DocumentCard to present a downloadable file.",
        "Use GoogleDocsCard to link to a Google Docs document.",
      ],
    },
    {
      name: "Research",
      components: ["DeepResearchCard"],
      notes: [
        "Use DeepResearchCard to present deep research results with tabs for enhanced results, original search, and metadata.",
      ],
    },
    {
      name: "Calendar",
      components: ["CalendarListFetchCard"],
      notes: [
        "Use CalendarListFetchCard to display a list of fetched calendar objects (not events).",
      ],
    },
    {
      name: "Social",
      components: ["TwitterSearchCard"],
      notes: [
        "Use TwitterSearchCard to display Twitter/X search results as tweet cards.",
      ],
    },
  ],
});
