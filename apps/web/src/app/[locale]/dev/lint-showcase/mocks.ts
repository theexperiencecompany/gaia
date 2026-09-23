import type { RateLimitData } from "@shared/chat";
import type { CalendarOptions } from "@/types/features/calendarTypes";
import type { EmailThreadData } from "@/types/features/mailTypes";
import type { TodoToolStats } from "@/types/features/todoToolTypes";
import type { TwitterTweetData } from "@/types/features/twitterTypes";

export const MOCK_TWEET: TwitterTweetData = {
  id: "1865432109876547890",
  text: "Ship the design-system fix once, in one place, and every surface improves together. Proud of this team.",
  created_at: "2026-09-14T16:20:00Z",
  author: {
    id: "42",
    username: "heygaia",
    name: "GAIA",
    verified: true,
  },
  public_metrics: {
    retweet_count: 48,
    reply_count: 12,
    like_count: 1240,
    quote_count: 6,
    bookmark_count: 30,
    impression_count: 88200,
  },
};

export const MOCK_CALENDAR_OPTIONS: CalendarOptions[] = [
  {
    summary: "Design review",
    description: "Weekly sync with the design team",
    start: "2026-09-16T10:00:00Z",
    end: "2026-09-16T11:30:00Z",
    calendar_id: "primary",
    calendar_name: "Work",
    background_color: "#00bbff",
  },
];

export const MOCK_TODO_STATS: TodoToolStats = {
  total: 18,
  completed: 11,
  pending: 7,
  overdue: 2,
  today: 4,
  upcoming: 3,
};

export const MOCK_RATE_LIMIT: RateLimitData = {
  feature: "deep_research",
  plan_required: "pro",
  current_plan: "free",
  reset_time: new Date(Date.now() + 45 * 60_000).toISOString(),
};

export const MOCK_EMAIL_THREAD: EmailThreadData = {
  thread_id: "thread_abc123",
  messages: [
    {
      id: "msg_001",
      from: "Priya Nair <priya@example.com>",
      subject: "Design review notes",
      time: "2026-09-15T09:30:00Z",
      snippet: "Here are the notes from today's review",
      body: "<p>Here are the notes from today's review. The new card contract looks great across every surface.</p>",
      content: {
        text: "Here are the notes from today's review.",
        html: "<p>Here are the notes from today's review. The new card contract looks great across every surface.</p>",
      },
    },
  ],
  messages_count: 1,
};
