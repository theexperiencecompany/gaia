import type { ApprovalRequestData } from "@shared/chat";
import type React from "react";
import type {
  MemoryData,
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
  SuggestedIntegration,
} from "@/features/integrations/types";
import EmailListCard from "@/features/mail/components/EmailListCard";
import { WeatherCard } from "@/features/weather/components/WeatherCard";
import WorkflowCreatedCard from "@/features/workflows/components/WorkflowCreatedCard";
import WorkflowDraftCard from "@/features/workflows/components/WorkflowDraftCard";
import type {
  EmailComposeData,
  EmailFetchData,
  EmailSentData,
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
import type { SearchResults } from "@/types/features/searchTypes";
import ApprovalRequestGroup from "../ApprovalRequestGroup";
import { CalendarDeleteSection } from "../CalendarDeleteSection";
import { CalendarEditSection } from "../CalendarEditSection";
import CalendarEventSection from "../CalendarEventSection";
import CodeExecutionSection from "../CodeExecutionSection";
import ContactListSection from "../ContactListSection";
import EmailComposeSection from "../EmailComposeSection";
import EmailSentSection from "../EmailSentSection";
import FileArtifactSection from "../FileArtifactSection";
import GoogleDocsSection from "../GoogleDocsSection";
import MemoryCard from "../MemoryCard";
import NotificationListSection from "../NotificationListSection";
import PeopleSearchSection from "../PeopleSearchSection";
import RateLimitCard from "../RateLimitCard";
import RedditCommentSection from "../RedditCommentSection";
import RedditCreatedSection from "../RedditCreatedSection";
import RedditPostSection from "../RedditPostSection";
import RedditSearchSection from "../RedditSearchSection";
import ScreenshotSection from "../ScreenshotSection";
import SendNotificationSection from "../SendNotificationSection";
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

// Map of tool_name -> renderer function for unified tool_data rendering.
// Renderers return ONE card per tool_data entry; sibling identity is owned by
// the keyed <React.Fragment> wrapper at the renderTool() call site (TextBubble),
// so renderers neither take nor set keys.
type RendererMap = {
  [K in ToolName]: (data: ToolDataMap[K]) => React.ReactNode;
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
  search_results: (data) => {
    const items = (Array.isArray(data) ? data : [data]) as SearchResults[];
    return <SearchResultsTabs search_results={mergeSearchResults(items)} />;
  },
  deep_research_results: (data) => (
    <DeepResearchResultsTabs deep_research_results={data} />
  ),

  // Weather
  weather_data: (data) => <WeatherCard weatherData={data} />,

  // Desktop
  screenshot_data: (data) => <ScreenshotSection screenshot_data={data} />,

  // Email
  email_thread_data: (data) => <EmailThreadCard emailThreadData={data} />,
  email_fetch_data: (data) => {
    // When grouped, data is EmailFetchData[][] — flatten batches into one list
    const emails = Array.isArray(data[0])
      ? (data as unknown as EmailFetchData[][]).flat()
      : data;
    return <EmailListCard emails={emails} />;
  },
  email_compose_data: (data) => {
    // When grouped, data is EmailComposeData[][] — flatten batches
    const items = Array.isArray(data[0])
      ? (data as unknown as EmailComposeData[][]).flat()
      : data;
    return <EmailComposeSection email_compose_data={items} />;
  },
  email_sent_data: (data) => {
    // When grouped, data is EmailSentData[][] — flatten batches
    const items = Array.isArray(data[0])
      ? (data as unknown as EmailSentData[][]).flat()
      : data;
    return <EmailSentSection email_sent_data={items} />;
  },
  contacts_data: (data) => (
    <ContactListSection contacts_data={Array.isArray(data) ? data : [data]} />
  ),
  people_search_data: (data) => (
    <PeopleSearchSection
      people_search_data={Array.isArray(data) ? data : [data]}
    />
  ),

  // Calendar
  calendar_options: (data) => <CalendarEventSection calendar_options={data} />,
  calendar_delete_options: (data) => (
    <CalendarDeleteSection calendar_delete_options={data} />
  ),
  calendar_edit_options: (data) => (
    <CalendarEditSection calendar_edit_options={data} />
  ),
  calendar_fetch_data: (data) => (
    <CalendarListCard events={Array.isArray(data) ? data : [data]} />
  ),
  calendar_list_fetch_data: (data) => (
    <CalendarListFetchCard calendars={Array.isArray(data) ? data : [data]} />
  ),

  // Support ticket
  support_ticket_data: (data) => (
    <SupportTicketSection support_ticket_data={data} />
  ),

  // Documents & Code
  google_docs_data: (data) => <GoogleDocsSection google_docs_data={data} />,
  code_data: (data) => <CodeExecutionSection code_data={data} />,
  artifact_data: (data) => <FileArtifactSection artifact_data={data} />,

  todo_data: (data) => (
    <TodoSection
      todos={data.todos}
      projects={data.projects}
      stats={data.stats}
      action={data.action}
      message={data.message}
    />
  ),
  notification_data: (data) => (
    <NotificationListSection
      notifications={
        (data as { notifications: unknown[] })
          .notifications as NotificationRecord[]
      }
      title="Your Notifications"
    />
  ),
  send_notification_data: (data) => (
    <SendNotificationSection send_notification_data={data} />
  ),
  integration_connection_required: (data) => {
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
            key={item.integration_id}
            integration_connection_required={item}
          />
        ))}
      </>
    );
  },

  integration_list_data: (data) => {
    // Handle grouped data (array of IntegrationListStreamData)
    const items = (
      Array.isArray(data) ? data : [data]
    ) as IntegrationListStreamData[];

    // Merge all suggested integrations and de-duplicate by id in one pass
    const seen = new Set<string>();
    const mergedSuggested: SuggestedIntegration[] = [];
    for (const item of items) {
      dedupePush(item.suggested ?? [], seen, (s) => s.id, mergedSuggested);
    }

    return <IntegrationListSection suggestedIntegrations={mergedSuggested} />;
  },

  // Twitter
  twitter_search_data: (data) => (
    <TwitterSearchSection twitter_search_data={data} />
  ),
  twitter_user_data: (data) => (
    <TwitterUserSection
      twitter_user_data={Array.isArray(data) ? data : [data]}
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

  workflow_draft: (data) => <WorkflowDraftCard draft={data} />,

  workflow_created: (data) => <WorkflowCreatedCard workflow={data} />,

  mcp_app: (data) => <MCPAppRenderer data={data} />,

  rate_limit_data: (data) => {
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
          <RateLimitCard key={item.feature || "unknown"} data={item} />
        ))}
      </>
    );
  },

  // Memory — multiple calls in one turn (e.g. several add_memory or a search
  // followed by an add) are grouped into one card with stacked action rows.
  memory_data: (data) => {
    const items = (Array.isArray(data) ? data : [data]) as MemoryData[];
    return <MemoryCard items={items} />;
  },

  // HIL approval — grouped so a run needing many decisions doesn't stack a full
  // card each: pending ones show side by side, settled ones are removed (the
  // assistant's reply already reflects them). Each approval_id is a single entry
  // (pending→resolved replaced in place via upsertApprovalToolData); grouping
  // collects them into the array.
  approval_request: (data) => {
    const raw = (Array.isArray(data) ? data : [data]) as ApprovalRequestData[];
    // A resumed stream replays the gate-time PENDING frame after the decision
    // already settled it — collapse by approval_id, settled wins over pending.
    // (Sibling identity is owned by the keyed wrapper at the call site.)
    const byId = new Map<string, ApprovalRequestData>();
    for (const item of raw) {
      const prev = byId.get(item.approval_id);
      if (!prev || prev.status === "pending" || item.status !== "pending") {
        byId.set(item.approval_id, item);
      }
    }
    return <ApprovalRequestGroup items={[...byId.values()]} />;
  },
};

/** Whether a tool_data entry has a card registered at all. A missing entry is a
 *  silent drop (`renderTool` returns null), which the render audit records. */
export function hasToolRenderer(name: ToolName): boolean {
  return name in TOOL_RENDERERS;
}

export function renderTool<K extends ToolName>(
  name: K,
  data: ToolDataMap[K],
  // Unused by renderers — sibling identity is owned by the keyed
  // <React.Fragment> wrapper at the call site. Kept in the signature only so
  // existing callers that still pass the tool_data index keep type-checking.
  _index?: number,
): React.ReactNode {
  const renderer = TOOL_RENDERERS[name];
  return renderer ? renderer(data) : null;
}
