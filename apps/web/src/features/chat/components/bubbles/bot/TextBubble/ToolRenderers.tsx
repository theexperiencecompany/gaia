import type React from "react";
import type {
  MCPAppData,
  RateLimitData,
  ToolDataMap,
  ToolName,
} from "@/config/registries/toolRegistry";
import CalendarListCard from "@/features/calendar/components/CalendarListCard";
import CalendarListFetchCard from "@/features/calendar/components/CalendarListFetchCard";
import DeepResearchResultsTabs from "@/features/chat/components/bubbles/bot/DeepResearchResultsTabs";
import EmailThreadCard from "@/features/chat/components/bubbles/bot/EmailThreadCard";
import IntegrationConnectionPrompt from "@/features/chat/components/bubbles/bot/IntegrationConnectionPrompt";
import SearchResultsTabs from "@/features/chat/components/bubbles/bot/SearchResultsTabs";
import { MCPAppRenderer } from "@/features/chat/components/tools/MCPAppRenderer";
import { IntegrationListSection } from "@/features/integrations/components/IntegrationListSection";
import type {
  IntegrationConnectionData,
  IntegrationListStreamData,
} from "@/features/integrations/types";
import EmailListCard from "@/features/mail/components/EmailListCard";
import { WeatherCard } from "@/features/weather/components/WeatherCard";
import WorkflowCreatedCard from "@/features/workflows/components/WorkflowCreatedCard";
import WorkflowDraftCard from "@/features/workflows/components/WorkflowDraftCard";
import type {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarFetchData,
} from "@/types/features/calendarTypes";
import type {
  ContactData,
  EmailComposeData,
  EmailFetchData,
  EmailSentData,
  EmailThreadData,
} from "@/types/features/mailTypes";
import type { NotificationRecord } from "@/types/features/notificationTypes";
import type {
  RedditCommentCreatedData,
  RedditCommentData,
  RedditData,
  RedditPostCreatedData,
  RedditPostData,
  RedditSearchData,
} from "@/types/features/redditTypes";
import type {
  DeepResearchResults,
  SearchResults,
} from "@/types/features/searchTypes";
import type {
  ArtifactData,
  GoalDataMessageType,
  GoogleDocsData,
  WorkflowDraftData,
} from "@/types/features/toolDataTypes";
import type {
  TwitterSearchData,
  TwitterUserData,
} from "@/types/features/twitterTypes";
import { CalendarDeleteSection } from "../CalendarDeleteSection";
import { CalendarEditSection } from "../CalendarEditSection";
import CalendarEventSection from "../CalendarEventSection";
import CodeExecutionSection from "../CodeExecutionSection";
import ContactListSection from "../ContactListSection";
import EmailComposeSection from "../EmailComposeSection";
import EmailSentSection from "../EmailSentSection";
import FileArtifactSection from "../FileArtifactSection";
import GoogleDocsSection from "../GoogleDocsSection";
import GoalSection from "../goals/GoalSection";
import type { GoalAction } from "../goals/types";
import NotificationListSection from "../NotificationListSection";
import PeopleSearchSection from "../PeopleSearchSection";
import RateLimitCard from "../RateLimitCard";
import RedditCommentSection from "../RedditCommentSection";
import RedditCreatedSection from "../RedditCreatedSection";
import RedditPostSection from "../RedditPostSection";
import RedditSearchSection from "../RedditSearchSection";
import SupportTicketSection from "../SupportTicketSection";
import TodoSection from "../TodoSection";
import TwitterSearchSection from "../TwitterSearchSection";
import TwitterUserSection from "../TwitterUserSection";

// Utility type: union of all possible tool_name/data pairs
export type ToolDataUnion = {
  [K in ToolName]: { tool_name: K; data: ToolDataMap[K] };
}[ToolName];

export function getTypedData<K extends ToolName>(
  entry: ToolDataUnion,
  toolName: K,
): ToolDataMap[K] | undefined {
  return entry.tool_name === toolName
    ? (entry.data as ToolDataMap[K])
    : undefined;
}

// Map of tool_name -> renderer function for unified tool_data rendering
type RendererMap = {
  [K in ToolName]: (data: ToolDataMap[K], index: number) => React.ReactNode;
};

// Push items into `target` only if their key hasn't been seen yet (shared dedupe set).
function dedupePush<T>(
  items: readonly T[],
  seen: Set<string>,
  getKey: (item: T) => string,
  target: T[],
): void {
  for (const item of items) {
    const key = getKey(item);
    if (seen.has(key)) continue;
    seen.add(key);
    target.push(item);
  }
}

// When the search_results tool was grouped (LLM emitted it multiple times in one
// turn), merge the batches into a single result set, deduping by URL across web /
// images / news.
function mergeSearchResults(items: readonly SearchResults[]): SearchResults {
  const seenUrls = new Set<string>();
  const merged: SearchResults = { web: [], images: [], news: [] };
  for (const item of items) {
    dedupePush(item.web ?? [], seenUrls, (r) => r.url, merged.web!);
    dedupePush(item.images ?? [], seenUrls, (img) => img, merged.images!);
    dedupePush(item.news ?? [], seenUrls, (n) => n.url, merged.news!);
  }
  return merged;
}

const TOOL_RENDERERS: Partial<RendererMap> = {
  // Search
  search_results: (data, index) => {
    const items = (Array.isArray(data) ? data : [data]) as SearchResults[];
    return (
      <SearchResultsTabs
        key={`tool-search-${index}`}
        search_results={mergeSearchResults(items)}
      />
    );
  },
  deep_research_results: (data, index) => (
    <DeepResearchResultsTabs
      key={`tool-deep-search-${index}`}
      deep_research_results={data as DeepResearchResults}
    />
  ),

  // Weather
  weather_data: (data, index) => (
    <WeatherCard key={`tool-weather-${index}`} weatherData={data} />
  ),

  // Email
  email_thread_data: (data, index) => (
    <EmailThreadCard
      key={`tool-email-thread-${index}`}
      emailThreadData={data as EmailThreadData}
    />
  ),
  email_fetch_data: (data, index) => {
    // When grouped, data is EmailFetchData[][] — flatten batches into one list
    const emails = Array.isArray(data[0])
      ? (data as unknown as EmailFetchData[][]).flat()
      : (data as EmailFetchData[]);
    return <EmailListCard key={`tool-email-fetch-${index}`} emails={emails} />;
  },
  email_compose_data: (data, index) => {
    // When grouped, data is EmailComposeData[][] — flatten batches
    const items = Array.isArray(data[0])
      ? (data as unknown as EmailComposeData[][]).flat()
      : (data as EmailComposeData[]);
    return (
      <EmailComposeSection
        key={`tool-email-compose-${index}`}
        email_compose_data={items}
      />
    );
  },
  email_sent_data: (data, index) => {
    // When grouped, data is EmailSentData[][] — flatten batches
    const items = Array.isArray(data[0])
      ? (data as unknown as EmailSentData[][]).flat()
      : (data as EmailSentData[]);
    return (
      <EmailSentSection
        key={`tool-email-sent-${index}`}
        email_sent_data={items}
      />
    );
  },
  contacts_data: (data, index) => (
    <ContactListSection
      key={`tool-contacts-${index}`}
      contacts_data={(Array.isArray(data) ? data : [data]) as ContactData[]}
    />
  ),
  people_search_data: (data, index) => (
    <PeopleSearchSection
      key={`tool-people-search-${index}`}
      people_search_data={Array.isArray(data) ? data : [data]}
    />
  ),

  // Calendar
  calendar_options: (data, index) => {
    return (
      <CalendarEventSection
        key={`tool-cal-options-${index}`}
        calendar_options={data}
      />
    );
  },
  calendar_delete_options: (data, index) => {
    return (
      <CalendarDeleteSection
        key={`tool-cal-del-${index}`}
        calendar_delete_options={data as CalendarDeleteOptions[]}
      />
    );
  },
  calendar_edit_options: (data, index) => {
    return (
      <CalendarEditSection
        key={`tool-cal-edit-${index}`}
        calendar_edit_options={data as CalendarEditOptions[]}
      />
    );
  },
  calendar_fetch_data: (data, index) => (
    <CalendarListCard
      key={`tool-cal-fetch-${index}`}
      events={(Array.isArray(data) ? data : [data]) as CalendarFetchData[]}
    />
  ),
  calendar_list_fetch_data: (data, index) => (
    <CalendarListFetchCard
      key={`tool-cal-list-${index}`}
      calendars={Array.isArray(data) ? data : [data]}
    />
  ),

  // Support ticket
  support_ticket_data: (data, index) => (
    <SupportTicketSection
      key={`tool-support-${index}`}
      support_ticket_data={data}
    />
  ),

  // Documents & Code
  google_docs_data: (data, index) => (
    <GoogleDocsSection
      key={`tool-gdocs-${index}`}
      google_docs_data={data as GoogleDocsData}
    />
  ),
  code_data: (data, index) => (
    <CodeExecutionSection key={`tool-code-${index}`} code_data={data} />
  ),
  artifact_data: (data, index) => (
    <FileArtifactSection
      key={`tool-artifact-${index}`}
      artifact_data={data as ArtifactData | ArtifactData[]}
    />
  ),

  todo_data: (data, index) => (
    <TodoSection
      key={`tool-todo-${index}`}
      todos={data.todos}
      projects={data.projects}
      stats={data.stats}
      action={data.action}
      message={data.message}
    />
  ),
  goal_data: (data, index) => {
    const g = data as GoalDataMessageType;
    return (
      <GoalSection
        key={`tool-goal-${index}`}
        goals={g.goals}
        stats={g.stats}
        action={g.action as GoalAction}
        message={g.message}
        goal_id={g.goal_id}
        deleted_goal_id={g.deleted_goal_id}
        error={g.error}
      />
    );
  },
  notification_data: (data, index) => (
    <NotificationListSection
      key={`tool-notifications-${index}`}
      notifications={
        (data as { notifications: unknown[] })
          .notifications as NotificationRecord[]
      }
      title="Your Notifications"
    />
  ),
  integration_connection_required: (data, index) => {
    // Data can be a single item or an array (when grouped)
    const items = (
      Array.isArray(data) ? data : [data]
    ) as IntegrationConnectionData[];
    // De-duplicate by integration_id
    const seen = new Set<string>();
    const uniqueItems = items.filter((item) => {
      if (seen.has(item.integration_id)) return false;
      seen.add(item.integration_id);
      return true;
    });
    return (
      <>
        {uniqueItems.map((item) => (
          <IntegrationConnectionPrompt
            key={`tool-integration-connection-${index}-${item.integration_id}`}
            integration_connection_required={item}
          />
        ))}
      </>
    );
  },

  integration_list_data: (data, index) => {
    // Handle grouped data (array of IntegrationListStreamData)
    const items = (
      Array.isArray(data) ? data : [data]
    ) as IntegrationListStreamData[];

    // Merge all suggested integrations and de-duplicate by id
    const seen = new Set<string>();
    const mergedSuggested = items
      .flatMap((item) => item.suggested || [])
      .filter((s) => {
        if (seen.has(s.id)) return false;
        seen.add(s.id);
        return true;
      });

    return (
      <IntegrationListSection
        key={`tool-integration-list-${index}`}
        suggestedIntegrations={mergedSuggested}
      />
    );
  },

  // Twitter
  twitter_search_data: (data, index) => (
    <TwitterSearchSection
      key={`tool-twitter-search-${index}`}
      twitter_search_data={data as TwitterSearchData}
    />
  ),
  twitter_user_data: (data, index) => (
    <TwitterUserSection
      key={`tool-twitter-users-${index}`}
      twitter_user_data={
        (Array.isArray(data) ? data : [data]) as TwitterUserData[]
      }
    />
  ),

  // tool_calls_data and subagent_group are handled together by UnifiedToolThread
  // (see processedTools logic below) — they are NOT rendered through TOOL_RENDERERS.

  reddit_data: (data) => {
    const items = (Array.isArray(data) ? data : [data]) as RedditData[];
    const groups: {
      search: RedditSearchData[];
      post: RedditPostData[];
      comments: RedditCommentData[];
      post_created: RedditPostCreatedData[];
      comment_created: RedditCommentCreatedData[];
    } = {
      search: [],
      post: [],
      comments: [],
      post_created: [],
      comment_created: [],
    };

    items.forEach((d) => {
      if (d.type === "search") groups.search.push(...d.posts);
      else if (d.type === "post") groups.post.push(d.post);
      else if (d.type === "comments") groups.comments.push(...d.comments);
      else if (d.type === "post_created") groups.post_created.push(d.data);
      else if (d.type === "comment_created")
        groups.comment_created.push(d.data);
    });

    return (
      <>
        {groups.search.length > 0 && (
          <RedditSearchSection reddit_search_data={groups.search} />
        )}
        {groups.post.map((post) => (
          <RedditPostSection key={post.id} reddit_post_data={post} />
        ))}
        {groups.comments.length > 0 && (
          <RedditCommentSection reddit_comment_data={groups.comments} />
        )}
        {(groups.post_created.length > 0 ||
          groups.comment_created.length > 0) && (
          <RedditCreatedSection
            posts={groups.post_created}
            comments={groups.comment_created}
          />
        )}
      </>
    );
  },

  workflow_draft: (data, index) => (
    <WorkflowDraftCard
      key={`tool-workflow-draft-${index}`}
      draft={data as WorkflowDraftData}
    />
  ),

  workflow_created: (data, index) => (
    <WorkflowCreatedCard
      key={`tool-workflow-created-${index}`}
      workflow={data}
    />
  ),

  mcp_app: (data, index) => (
    <MCPAppRenderer
      key={`tool-mcp-app-${(data as MCPAppData).tool_call_id || index}`}
      data={data as MCPAppData}
    />
  ),

  rate_limit_data: (data, index) => {
    // When grouped, data is RateLimitData[] — deduplicate by feature
    const items = (Array.isArray(data) ? data : [data]) as RateLimitData[];
    const seen = new Set<string>();
    const unique = items.filter((item) => {
      const key = item.feature || "unknown";
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    return (
      <>
        {unique.map((item) => (
          <RateLimitCard
            key={`tool-rate-limit-${index}-${item.feature ?? "unknown"}`}
            data={item}
          />
        ))}
      </>
    );
  },
};

export function renderTool<K extends ToolName>(
  name: K,
  data: ToolDataMap[K],
  index: number,
): React.ReactNode {
  const renderer = TOOL_RENDERERS[name] as
    | ((data: ToolDataMap[K], index: number) => React.ReactNode)
    | undefined;
  return renderer ? renderer(data, index) : null;
}
