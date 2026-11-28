import type {
  RedditCardComment,
  RedditCardCommentCreated,
  RedditCardPost,
  RedditCardPostCreated,
  RedditCardSearchPost,
  SearchResultsData,
  SuggestedIntegrationCard,
} from "@shared/api/generated";
import { ArtifactCardDataSchema } from "@shared/chat";
import dynamic from "next/dynamic";
import type React from "react";
import type { ToolDataMap, ToolName } from "@/config/registries/toolRegistry";
import CalendarListCard from "@/features/calendar/components/CalendarListCard";
import { ArtifactCard } from "@/features/chat/components/artifacts/ArtifactCard";
import ConnectOptions from "@/features/chat/components/bubbles/bot/ConnectOptions";
import DeepResearchResultsTabs from "@/features/chat/components/bubbles/bot/DeepResearchResultsTabs";
import { DeviceApprovalPrompt } from "@/features/chat/components/bubbles/bot/DeviceApprovalPrompt";
import { DeviceOnboardingPrompt } from "@/features/chat/components/bubbles/bot/DeviceOnboardingPrompt";
import EmailThreadCard from "@/features/chat/components/bubbles/bot/EmailThreadCard";
import IntegrationConnectionPrompt from "@/features/chat/components/bubbles/bot/IntegrationConnectionPrompt";
import SearchResultsTabs from "@/features/chat/components/bubbles/bot/SearchResultsTabs";
import { MCPAppLoading } from "@/features/chat/components/tools/MCPAppLoading";
import { IntegrationListSection } from "@/features/integrations/components/IntegrationListSection";
import EmailListCard from "@/features/mail/components/EmailListCard";
import { WeatherCard } from "@/features/weather/components/WeatherCard";
import WorkflowCreatedCard from "@/features/workflows/components/WorkflowCreatedCard";
import WorkflowDraftCard from "@/features/workflows/components/WorkflowDraftCard";
import ApprovalRequestGroup from "../ApprovalRequestGroup";
import { BriefMessageCard } from "../BriefMessageCard";
import BrowserTaskSection from "../BrowserTaskSection";
import { CalendarDeleteSection } from "../CalendarDeleteSection";
import { CalendarEditSection } from "../CalendarEditSection";
import { CalendarEventReadonlySection } from "../CalendarEventReadonlySection";
import { CalendarListFetchSection } from "../CalendarListFetchSection";
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

// @mcp-ui/client ships its own zod, whose eval probe the CSP reports; load it only when an MCP app renders.
// Its own loading card keeps the suspend local instead of blanking the surrounding messages.
const MCPAppRenderer = dynamic(
  () =>
    import("@/features/chat/components/tools/MCPAppRenderer").then(
      (m) => m.MCPAppRenderer,
    ),
  { ssr: false, loading: MCPAppLoading },
);

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

// Map of tool_name -> renderer for unified tool_data rendering. Renderers
// return ONE card per entry; sibling identity is owned by the keyed
// <React.Fragment> at renderTool()'s call site (TextBubble) — no keys here.
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
function mergeSearchResults(
  items: readonly SearchResultsData[],
): Pick<SearchResultsData, "web" | "images" | "news"> {
  const seenUrls = new Set<string>();
  const merged: Pick<SearchResultsData, "web" | "images" | "news"> = {
    web: [],
    images: [],
    news: [],
  };
  for (const item of items) {
    dedupePush(item.web ?? [], seenUrls, (r) => r.url, merged.web);
    dedupePush(item.images ?? [], seenUrls, (img) => img, merged.images);
    dedupePush(item.news ?? [], seenUrls, (n) => n.url, merged.news);
  }
  return merged;
}

const TOOL_RENDERERS: Partial<RendererMap> = {
  // Search
  search_results: (data) => (
    <SearchResultsTabs search_results={mergeSearchResults(data)} />
  ),
  deep_research_results: (data) => (
    <DeepResearchResultsTabs deep_research_results={data} />
  ),

  // Weather
  weather_data: (data) => <WeatherCard weatherData={data} />,

  // Desktop
  screenshot_data: (data) => <ScreenshotSection screenshot_data={data} />,

  // Browser automation (Browser-Use)
  browser_task_data: (data) => <BrowserTaskSection data={data} />,

  // Email
  email_thread_data: (data) => <EmailThreadCard emailThreadData={data} />,
  // Grouped: one batch per call, flattened into one list.
  email_fetch_data: (data) => <EmailListCard emails={data.flat()} />,
  email_compose_data: (data) => (
    <EmailComposeSection email_compose_data={data.flat()} />
  ),
  email_sent_data: (data) => <EmailSentSection email_sent_data={data.flat()} />,
  contacts_data: (data) => <ContactListSection contacts_data={data} />,
  people_search_data: (data) => (
    <PeopleSearchSection people_search_data={data} />
  ),

  // Calendar
  calendar_options: (data) => (
    <CalendarEventReadonlySection calendar_options={data} />
  ),
  calendar_delete_options: (data) => (
    <CalendarDeleteSection calendar_delete_options={data} />
  ),
  calendar_edit_options: (data) => (
    <CalendarEditSection calendar_edit_options={data} />
  ),
  calendar_fetch_data: (data) => <CalendarListCard events={data} />,
  calendar_list_fetch_data: (data) => (
    <CalendarListFetchSection calendars={data} />
  ),

  // Support ticket
  support_ticket_data: (data) => (
    <SupportTicketSection support_ticket_data={data} />
  ),

  // Documents & Code
  google_docs_data: (data) => <GoogleDocsSection google_docs_data={data} />,
  code_data: (data) => <CodeExecutionSection code_data={data} />,
  artifact_data: (data) => <FileArtifactSection artifact_data={data} />,
  artifact_done: (data) => (
    <ArtifactCard card={ArtifactCardDataSchema.parse(data)} />
  ),

  todo_data: (data) => <TodoSection card={data} />,
  notification_data: (data) => (
    <NotificationListSection
      notifications={data.notifications}
      title="Your Notifications"
    />
  ),
  send_notification_data: (data) => (
    <SendNotificationSection send_notification_data={data} />
  ),
  briefing_data: (data) => <BriefMessageCard data={data} />,
  connect_options: (data) => <ConnectOptions connect_options={data} />,
  integration_connection_required: (data) => {
    // Grouped: de-duplicate by integration_id
    const seen = new Set<string>();
    const uniqueItems = data.filter((item) => {
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

  // Device onboarding is a single instructional card (install → pair → approve);
  // not grouped, so `data` is one payload. It routes to the authenticated approve
  // page rather than approving inline.
  device_onboarding_required: (data) => (
    <DeviceOnboardingPrompt device_onboarding_required={data} />
  ),

  device_approval_required: (data) => {
    // Grouped: a resumed stream can replay the same waiting-device frame, so
    // de-duplicate by pairing code.
    const seen = new Set<string>();
    const uniqueItems = data.filter((item) => {
      if (seen.has(item.code)) return false;
      seen.add(item.code);
      return true;
    });
    return (
      <>
        {uniqueItems.map((item) => (
          <DeviceApprovalPrompt
            key={item.code}
            device_approval_required={item}
          />
        ))}
      </>
    );
  },

  integration_list_data: (data) => {
    // Grouped: merge all suggested integrations and de-duplicate by id in one pass
    const seen = new Set<string>();
    const mergedSuggested: SuggestedIntegrationCard[] = [];
    for (const item of data) {
      dedupePush(item.suggested ?? [], seen, (s) => s.id, mergedSuggested);
    }

    return <IntegrationListSection suggestedIntegrations={mergedSuggested} />;
  },

  // Twitter
  twitter_search_data: (data) => (
    <TwitterSearchSection twitter_search_data={data} />
  ),
  twitter_user_data: (data) => <TwitterUserSection twitter_user_data={data} />,

  // tool_calls_data and subagent_group are handled together by UnifiedToolThread
  // (see processedTools logic below) — they are NOT rendered through TOOL_RENDERERS.

  reddit_data: (data) => {
    const groups: {
      search: RedditCardSearchPost[];
      post: RedditCardPost[];
      comments: RedditCardComment[];
      post_created: RedditCardPostCreated[];
      comment_created: RedditCardCommentCreated[];
    } = {
      search: [],
      post: [],
      comments: [],
      post_created: [],
      comment_created: [],
    };

    data.forEach((d) => {
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
    // Grouped: deduplicate by feature
    const seen = new Set<string>();
    const unique = data.filter((item) => {
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
  memory_data: (data) => <MemoryCard items={data} />,

  // HIL approval — grouped so many decisions don't stack a full card each:
  // pending show side by side, settled are removed (reply reflects them).
  // The screen draws exactly one card per approval, from its log entries.
  approval_request: (data) => <ApprovalRequestGroup items={data} />,
};

/** Whether a card's tool has a renderer registered at all. A missing one is a
 *  silent drop (`renderTool` returns null), which the render audit records. */
export function hasToolRenderer(name: string): boolean {
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
