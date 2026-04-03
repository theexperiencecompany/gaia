// Utility type: union of all possible tool_name/data pairs
type ToolDataUnion = {
  [K in ToolName]: { tool_name: K; data: ToolDataMap[K] };
}[ToolName];

function getTypedData<K extends ToolName>(
  entry: ToolDataUnion,
  toolName: K,
): ToolDataMap[K] | undefined {
  return entry.tool_name === toolName
    ? (entry.data as ToolDataMap[K])
    : undefined;
}

import { Chip } from "@heroui/chip";
import { Alert01Icon } from "@icons";
import React, { useId } from "react";
// import { PostHogCaptureOnViewed } from "posthog-js/react";
import {
  GROUPED_TOOLS,
  type MCPAppData,
  type RateLimitData,
  type SubagentGroupData,
  type ToolCallEntry,
  type ToolDataEntry,
  type ToolDataMap,
  type ToolName,
} from "@/config/registries/toolRegistry";
import CalendarListCard from "@/features/calendar/components/CalendarListCard";
import CalendarListFetchCard from "@/features/calendar/components/CalendarListFetchCard";
import DeepResearchResultsTabs from "@/features/chat/components/bubbles/bot/DeepResearchResultsTabs";
import EmailThreadCard from "@/features/chat/components/bubbles/bot/EmailThreadCard";
import IntegrationConnectionPrompt from "@/features/chat/components/bubbles/bot/IntegrationConnectionPrompt";
import SearchResultsTabs from "@/features/chat/components/bubbles/bot/SearchResultsTabs";
import ThinkingBubble from "@/features/chat/components/bubbles/bot/ThinkingBubble";
import { MCPAppRenderer } from "@/features/chat/components/tools/MCPAppRenderer";
import { getEmojiCount, isOnlyEmojis } from "@/features/chat/utils/emojiUtils";
import { splitMessageByBreaks } from "@/features/chat/utils/messageBreakUtils";
import { shouldShowTextBubble } from "@/features/chat/utils/messageContentUtils";
import { parseThinkingFromText } from "@/features/chat/utils/thinkingParser";
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
  CalendarListFetchData,
  CalendarOptions,
} from "@/types/features/calendarTypes";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import type {
  ContactData,
  EmailComposeData,
  EmailFetchData,
  EmailSentData,
  EmailThreadData,
  PeopleSearchData,
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
import type { SupportTicketData } from "@/types/features/supportTypes";
import type { TodoProgressData } from "@/types/features/todoProgressTypes";
import type { TodoToolData } from "@/types/features/todoToolTypes";
import type {
  ArtifactData,
  CodeData,
  DocumentData,
  GoalDataMessageType,
  GoogleDocsData,
  WorkflowCreatedData,
  WorkflowDraftData,
} from "@/types/features/toolDataTypes";
import type {
  TwitterSearchData,
  TwitterUserData,
} from "@/types/features/twitterTypes";
import type { WeatherData } from "@/types/features/weatherTypes";
import MarkdownRenderer from "../../interface/MarkdownRenderer";
import { CalendarDeleteSection } from "./CalendarDeleteSection";
import { CalendarEditSection } from "./CalendarEditSection";
import CalendarEventSection from "./CalendarEventSection";
import CodeExecutionSection from "./CodeExecutionSection";
import ContactListSection from "./ContactListSection";
import DocumentSection from "./DocumentSection";
import EmailComposeSection from "./EmailComposeSection";
import EmailSentSection from "./EmailSentSection";
import FileArtifactSection from "./FileArtifactSection";
import GoogleDocsSection from "./GoogleDocsSection";
import GoalSection from "./goals/GoalSection";
import type { GoalAction } from "./goals/types";
import NotificationListSection from "./NotificationListSection";
import PeopleSearchSection from "./PeopleSearchSection";
import RateLimitCard from "./RateLimitCard";
import RedditCommentSection from "./RedditCommentSection";
import RedditCreatedSection from "./RedditCreatedSection";
import RedditPostSection from "./RedditPostSection";
import RedditSearchSection from "./RedditSearchSection";
import SupportTicketSection from "./SupportTicketSection";
import TodoProgressSection from "./TodoProgressSection";
import TodoSection from "./TodoSection";
import TwitterSearchSection from "./TwitterSearchSection";
import TwitterUserSection from "./TwitterUserSection";
import UnifiedToolThread from "./UnifiedToolThread";

// Map of tool_name -> renderer function for unified tool_data rendering
type RendererMap = {
  [K in ToolName]: (data: ToolDataMap[K], index: number) => React.ReactNode;
};
const TOOL_RENDERERS: Partial<RendererMap> = {
  // Search
  search_results: (data, index) => {
    // When grouped, data is SearchResults[] — merge and dedup
    const items = (Array.isArray(data) ? data : [data]) as SearchResults[];
    const seenUrls = new Set<string>();
    const merged: SearchResults = { web: [], images: [], news: [] };
    for (const item of items) {
      for (const r of item.web ?? []) {
        if (!seenUrls.has(r.url)) {
          seenUrls.add(r.url);
          merged.web!.push(r);
        }
      }
      for (const img of item.images ?? []) {
        if (!seenUrls.has(img)) {
          seenUrls.add(img);
          merged.images!.push(img);
        }
      }
      for (const n of item.news ?? []) {
        if (!seenUrls.has(n.url)) {
          seenUrls.add(n.url);
          merged.news!.push(n);
        }
      }
    }
    return (
      <SearchResultsTabs key={`tool-search-${index}`} search_results={merged} />
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
    <WeatherCard
      key={`tool-weather-${index}`}
      weatherData={data as WeatherData}
    />
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
      people_search_data={
        (Array.isArray(data) ? data : [data]) as PeopleSearchData[]
      }
    />
  ),

  // Calendar
  calendar_options: (data, index) => {
    return (
      <CalendarEventSection
        key={`tool-cal-options-${index}`}
        calendar_options={data as CalendarOptions[]}
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
      calendars={
        (Array.isArray(data) ? data : [data]) as CalendarListFetchData[]
      }
    />
  ),

  // Support ticket
  support_ticket_data: (data, index) => (
    <SupportTicketSection
      key={`tool-support-${index}`}
      support_ticket_data={data as SupportTicketData[]}
    />
  ),

  // Documents & Code
  document_data: (data, index) => (
    <DocumentSection
      key={`tool-doc-${index}`}
      document_data={data as DocumentData}
    />
  ),
  google_docs_data: (data, index) => (
    <GoogleDocsSection
      key={`tool-gdocs-${index}`}
      google_docs_data={data as GoogleDocsData}
    />
  ),
  code_data: (data, index) => (
    <CodeExecutionSection
      key={`tool-code-${index}`}
      code_data={data as CodeData}
    />
  ),
  artifact_data: (data, index) => (
    <FileArtifactSection
      key={`tool-artifact-${index}`}
      artifact_data={data as ArtifactData | ArtifactData[]}
    />
  ),

  todo_data: (data, index) => {
    const t = data as TodoToolData;
    return (
      <TodoSection
        key={`tool-todo-${index}`}
        todos={t.todos}
        projects={t.projects}
        stats={t.stats}
        action={t.action}
        message={t.message}
      />
    );
  },
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
      workflow={data as WorkflowCreatedData}
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

function renderTool<K extends ToolName>(
  name: K,
  data: ToolDataMap[K],
  index: number,
): React.ReactNode {
  const renderer = TOOL_RENDERERS[name] as
    | ((data: ToolDataMap[K], index: number) => React.ReactNode)
    | undefined;
  return renderer ? renderer(data, index) : null;
}

const REPLY_QUOTE_MAX_LENGTH = 40;

/** Inline reply quote shown at the top of a bot bubble, scrolls to the original message on click. */
function ReplyQuote({
  replyToMessage,
}: {
  replyToMessage: { id: string; content: string; role: "user" | "assistant" };
}) {
  const truncated =
    replyToMessage.content.length > REPLY_QUOTE_MAX_LENGTH
      ? `${replyToMessage.content.slice(0, REPLY_QUOTE_MAX_LENGTH).trim()}...`
      : replyToMessage.content;

  return (
    <button
      type="button"
      className="-mx-5 mb-2 flex w-[calc(100%+40px)] cursor-pointer items-start rounded-md border-l-2 border-zinc-400 bg-zinc-700/50 py-1.5 pl-2.5 pr-3 text-left"
      onClick={() => {
        const el = document.getElementById(replyToMessage.id);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          el.style.transition = "all 0.3s ease";
          el.style.scale = "1.02";
          setTimeout(() => {
            el.style.scale = "1";
          }, 300);
        }
      }}
    >
      <div className="flex flex-col overflow-hidden">
        <span className="text-[11px] font-semibold text-zinc-400">
          {replyToMessage.role === "user" ? "You" : "GAIA"}
        </span>
        <span className="truncate text-[12px] text-zinc-500">{truncated}</span>
      </div>
    </button>
  );
}

export default function TextBubble({
  text,
  disclaimer,
  tool_data,
  isConvoSystemGenerated,
  systemPurpose,
  loading,
  replyToMessage,
}: ChatBubbleBotProps) {
  const baseId = useId();

  // Parse thinking content from text
  const parsedContent = React.useMemo(() => {
    return parseThinkingFromText(text?.toString() || "");
  }, [text]);

  // Separate tool_calls_data + subagent_group from other tool_data entries.
  // The former are merged into a single UnifiedToolThread component.
  const { unifiedToolCalls, unifiedSubagentGroups, processedTools } =
    React.useMemo(() => {
      const grouped = new Map<ToolName, ToolDataMap[ToolName][]>();
      const individual: ToolDataEntry[] = [];
      const toolCalls: ToolCallEntry[] = [];
      const subagentGroups: SubagentGroupData[] = [];

      tool_data?.forEach((entry) => {
        const toolName = entry.tool_name as ToolName;

        // Collect tool_calls_data into a flat array
        if (toolName === "tool_calls_data") {
          const calls = Array.isArray(entry.data)
            ? (entry.data as ToolCallEntry[])
            : [entry.data as ToolCallEntry];
          toolCalls.push(...calls);
          return;
        }

        // Collect subagent_group entries
        if (toolName === "subagent_group") {
          subagentGroups.push(entry.data as SubagentGroupData);
          return;
        }

        if (GROUPED_TOOLS.has(toolName)) {
          if (!grouped.has(toolName)) grouped.set(toolName, []);
          grouped.get(toolName)!.push(entry.data);
        } else {
          individual.push(entry);
        }
      });

      const groupedEntries: ToolDataEntry[] = Array.from(grouped.entries()).map(
        ([toolName, dataArray]) => ({
          tool_name: toolName,
          tool_category: "",
          data: dataArray as ToolDataMap[ToolName],
          timestamp: null,
        }),
      );

      // Enriched type adds handoff_input/output to subagent groups
      type Enriched = SubagentGroupData & {
        handoff_input?: string;
        handoff_output?: string;
        nested_subagents: Enriched[];
      };

      // If backend provided subagent_group entries, use them.
      // Otherwise, synthesize groups from flat tool calls using
      // "Handing off to X" / "Spawning subagent" as delimiters.
      let finalToolCalls: ToolCallEntry[] = toolCalls;
      let finalGroups: Enriched[] = [];

      if (subagentGroups.length > 0) {
        // --- Backend-provided groups: deduplicate + enrich ---
        const subagentToolCallIds = new Set<string>();
        const collectIds = (groups: SubagentGroupData[]) => {
          for (const g of groups) {
            for (const tc of g.tool_calls) {
              if (tc.tool_call_id) subagentToolCallIds.add(tc.tool_call_id);
            }
            collectIds(g.nested_subagents);
          }
        };
        collectIds(subagentGroups);

        finalToolCalls =
          subagentToolCallIds.size > 0
            ? toolCalls.filter(
                (tc) =>
                  !tc.tool_call_id || !subagentToolCallIds.has(tc.tool_call_id),
              )
            : toolCalls;

        const deepEnrich = (g: SubagentGroupData): Enriched => ({
          ...g,
          nested_subagents: g.nested_subagents.map(deepEnrich),
        });
        finalGroups = subagentGroups.map(deepEnrich);

        // Enrich with input/output from handoff/spawn tool calls
        const allGroups: Enriched[] = [];
        const collectAll = (groups: Enriched[]) => {
          for (const g of groups) {
            allGroups.push(g);
            collectAll(g.nested_subagents);
          }
        };
        collectAll(finalGroups);

        const remaining: ToolCallEntry[] = [];
        const unmatchedSpawned = allGroups.filter(
          (g) => g.agent_type === "spawned",
        );
        let si = 0;
        for (const tc of finalToolCalls) {
          const msg = (tc.message || "").toLowerCase();
          const isHandoff =
            tc.tool_name === "handoff" || msg.startsWith("handing off to");
          const isSpawn =
            tc.tool_name === "spawn_subagent" || msg === "spawning subagent";
          if (!isHandoff && !isSpawn) {
            remaining.push(tc);
            continue;
          }
          const task =
            tc.inputs && typeof tc.inputs === "object"
              ? (tc.inputs as Record<string, unknown>).task
              : undefined;
          const output = tc.output;
          if (isHandoff) {
            const matched = allGroups.find(
              (g) =>
                g.agent_type === "handoff" &&
                msg.includes(g.subagent_name.toLowerCase()),
            );
            if (matched) {
              if (typeof task === "string" && task)
                matched.handoff_input = task;
              if (output) matched.handoff_output = output;
            }
          } else if (si < unmatchedSpawned.length) {
            const matched = unmatchedSpawned[si++];
            if (typeof task === "string" && task) matched.handoff_input = task;
            if (output) matched.handoff_output = output;
          }
        }
        finalToolCalls = remaining;

        // Frontend nesting inference: if spawned subagents are at the root level but
        // a handoff group contains a spawn_subagent tool call, nest them inside that group.
        // This handles data saved before parent_subagent_id was propagated correctly.
        const rootSpawned = finalGroups.filter(
          (g) => g.agent_type === "spawned",
        );
        if (rootSpawned.length > 0) {
          let spawnIdx = 0;
          for (const g of finalGroups) {
            if (g.agent_type !== "handoff") continue;
            const hasSpawnCall = g.tool_calls.some(
              (tc) => tc.tool_name === "spawn_subagent",
            );
            if (!hasSpawnCall || spawnIdx >= rootSpawned.length) continue;
            // Move the next unmatched spawned subagent into this group
            const spawned = rootSpawned[spawnIdx++];
            g.nested_subagents.push(spawned as Enriched);
          }
          // Remove nested spawned groups from the root list
          const nestedIds = new Set(
            finalGroups
              .filter((g) => g.agent_type === "handoff")
              .flatMap((g) => g.nested_subagents.map((n) => n.subagent_id)),
          );
          finalGroups = finalGroups.filter(
            (g) => !nestedIds.has(g.subagent_id),
          );
        }
      } else if (toolCalls.length > 0) {
        // --- No backend groups: synthesize from flat tool calls ---
        // "Handing off to X" starts a handoff group; subsequent tool calls
        // with matching tool_category go into that group.
        // "Spawning subagent" starts a spawned group; subsequent tool calls
        // until next handoff/spawn or end go into that group.
        const topLevel: ToolCallEntry[] = [];
        const syntheticGroups: Enriched[] = [];
        let currentGroup: Enriched | null = null;

        for (const tc of toolCalls) {
          const msg = (tc.message || "").toLowerCase();
          const isHandoff =
            tc.tool_name === "handoff" || msg.startsWith("handing off to");
          const isSpawn =
            tc.tool_name === "spawn_subagent" || msg === "spawning subagent";

          if (isHandoff) {
            // Close previous group
            if (currentGroup) {
              syntheticGroups.push(currentGroup);
              currentGroup = null;
            }
            // Extract name from "Handing off to {Name}"
            const nameMatch = (tc.message || "").match(/handing off to (.+)/i);
            const name = nameMatch ? nameMatch[1] : "Subagent";
            const task =
              tc.inputs && typeof tc.inputs === "object"
                ? (tc.inputs as Record<string, unknown>).task
                : undefined;
            currentGroup = {
              subagent_id: tc.tool_call_id || `synth-${syntheticGroups.length}`,
              subagent_name: name,
              agent_type: "handoff",
              tool_calls: [],
              duration_ms: null,
              token_count: null,
              started_at: "",
              completed_at: "synthetic",
              icon_url: null,
              tool_category: null,
              nested_subagents: [],
              handoff_input: typeof task === "string" ? task : undefined,
              handoff_output: tc.output || undefined,
            };
          } else if (isSpawn) {
            // Spawned subagent — nest inside current handoff if one is active
            const task =
              tc.inputs && typeof tc.inputs === "object"
                ? (tc.inputs as Record<string, unknown>).task
                : undefined;
            const spawnGroup: Enriched = {
              subagent_id:
                tc.tool_call_id || `synth-spawn-${syntheticGroups.length}`,
              subagent_name: "Task Agent",
              agent_type: "spawned",
              tool_calls: [],
              duration_ms: null,
              token_count: null,
              started_at: "",
              completed_at: "synthetic",
              icon_url: null,
              tool_category: "spawn_subagent",
              nested_subagents: [],
              handoff_input: typeof task === "string" ? task : undefined,
              handoff_output: tc.output || undefined,
            };
            if (currentGroup) {
              currentGroup.nested_subagents.push(spawnGroup);
            } else {
              syntheticGroups.push(spawnGroup);
            }
          } else if (currentGroup) {
            // Tool call belongs to the current group
            currentGroup.tool_calls.push(tc);
          } else {
            topLevel.push(tc);
          }
        }
        if (currentGroup) syntheticGroups.push(currentGroup);

        // Infer tool_category for handoff groups from their tool calls
        for (const g of syntheticGroups) {
          if (g.agent_type === "handoff" && g.tool_calls.length > 0) {
            const cat = g.tool_calls.find(
              (tc) =>
                tc.tool_category &&
                tc.tool_category !== "unknown" &&
                tc.tool_category !== "plan_tasks" &&
                tc.tool_category !== "retrieve_tools",
            )?.tool_category;
            if (cat) g.tool_category = cat;
          }
        }

        finalToolCalls = topLevel;
        finalGroups = syntheticGroups;
      }

      return {
        unifiedToolCalls: finalToolCalls,
        unifiedSubagentGroups: finalGroups,
        processedTools: [...groupedEntries, ...individual],
      };
    }, [tool_data]);

  return (
    <>
      {parsedContent.thinking && (
        <ThinkingBubble thinkingContent={parsedContent.thinking} />
      )}

      {/* Unified tool thread — merges tool_calls_data + subagent_group */}
      {(unifiedToolCalls.length > 0 || unifiedSubagentGroups.length > 0) && (
        <UnifiedToolThread
          key={`${baseId}-unified-tools`}
          tool_calls={unifiedToolCalls}
          subagent_groups={unifiedSubagentGroups}
        />
      )}

      {processedTools.map((entry, index) => {
        const toolName = entry.tool_name as ToolName;
        const keyId = entry.timestamp || index;

        if (toolName === "todo_progress") {
          const data = getTypedData(entry as ToolDataUnion, "todo_progress");
          return data ? (
            <React.Fragment key={`${baseId}-tool-${toolName}-${keyId}`}>
              <TodoProgressSection
                todo_progress={data as TodoProgressData}
                isStreaming={loading}
              />
            </React.Fragment>
          ) : null;
        }

        const renderer = TOOL_RENDERERS[toolName];
        if (!renderer) return null;

        const typedData = getTypedData(entry as ToolDataUnion, toolName);
        if (!typedData) return null;

        const toolCallId =
          typeof typedData === "object" &&
          typedData !== null &&
          "tool_call_id" in typedData
            ? String(
                (typedData as unknown as { tool_call_id?: string })
                  .tool_call_id ?? "",
              )
            : "";
        const toolKey = toolCallId
          ? `${baseId}-tool-${toolName}-${toolCallId}`
          : `${baseId}-tool-${toolName}-${index}`;

        return (
          <React.Fragment key={toolKey}>
            {renderTool(toolName, typedData, index)}
          </React.Fragment>
        );
      })}

      {shouldShowTextBubble(text, isConvoSystemGenerated, systemPurpose) &&
        (() => {
          // Use cleaned text without thinking tags
          const displayText = parsedContent.cleanText || "";
          const textParts = splitMessageByBreaks(displayText);
          // const hasMultipleParts = textParts.length > 1;

          const renderBubbleContent = (
            content: string,
            showDisclaimer: boolean,
          ) => (
            <div className="flex flex-col gap-3">
              <MarkdownRenderer content={content} isStreaming={loading} />
              {!!disclaimer && showDisclaimer && (
                <Chip
                  className="text-xs font-medium text-warning-500"
                  color="warning"
                  size="sm"
                  startContent={
                    <Alert01Icon className="text-warning-500" height={17} />
                  }
                  variant="flat"
                >
                  {disclaimer}
                </Chip>
              )}
            </div>
          );

          return (
            <div className="flex flex-col">
              {textParts.map((part, index) => {
                const isFirst = index === 0;
                const isLast = index === textParts.length - 1;
                const isSingle = textParts.length === 1;

                // Emoji detection for this specific part
                const isEmojiOnly = isOnlyEmojis(part);
                const emojiCount = isEmojiOnly ? getEmojiCount(part) : 0;

                // Single message should show tail (use last styling)
                // Otherwise: first = no tail, middle = no tail, last = show tail
                let groupedClasses = isSingle
                  ? "imessage-grouped-last"
                  : isFirst
                    ? "imessage-grouped-first mb-1.5"
                    : isLast
                      ? "imessage-grouped-last"
                      : "imessage-grouped-middle mb-1.5";

                let bubbleClassName = "imessage-bubble imessage-from-them";

                // Construct styles for emoji-only messages
                let textClass = "";

                if (isEmojiOnly) {
                  if (emojiCount === 1) {
                    bubbleClassName = "select-none";
                    groupedClasses = "";
                    textClass = "text-[4rem] leading-none";
                  } else if (emojiCount === 2) {
                    textClass = "text-5xl";
                  } else if (emojiCount === 3) {
                    textClass = "text-4xl";
                  }
                }

                return (
                  <div
                    // biome-ignore lint/suspicious/noArrayIndexKey: array is stable
                    key={`${baseId}-text-part-${index}`}
                    className={`${bubbleClassName} ${groupedClasses}`}
                  >
                    {/* Reply quote: full-width card with left accent border, scrolls to original on click */}
                    {isFirst && replyToMessage?.content && (
                      <ReplyQuote replyToMessage={replyToMessage} />
                    )}
                    <div className={textClass}>
                      {renderBubbleContent(part, isLast)}
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })()}
    </>
  );
}
