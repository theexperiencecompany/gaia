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
import React, { useId } from "react";

// import { PostHogCaptureOnViewed } from "posthog-js/react";
import {
  GROUPED_TOOLS,
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
import { splitMessageByBreaks } from "@/features/chat/utils/messageBreakUtils";
import { shouldShowTextBubble } from "@/features/chat/utils/messageContentUtils";
import { parseThinkingFromText } from "@/features/chat/utils/thinkingParser";
import { IntegrationListSection } from "@/features/integrations";
import EmailListCard from "@/features/mail/components/EmailListCard";
import { WeatherCard } from "@/features/weather/components/WeatherCard";
import { Alert01Icon } from "@/icons";
import type {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarOptions,
  CodeData,
  DeepResearchResults,
  DocumentData,
  EmailComposeData,
  EmailSentData,
  EmailThreadData,
  GoalDataMessageType,
  GoogleDocsData,
  SearchResults,
  TodoToolData,
  WeatherData,
} from "@/types";
import type {
  CalendarFetchData,
  CalendarListFetchData,
} from "@/types/features/calendarTypes";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import type { IntegrationConnectionData } from "@/types/features/integrationTypes";
import type {
  ContactData,
  EmailFetchData,
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
import type { SupportTicketData } from "@/types/features/supportTypes";

import MarkdownRenderer from "../../interface/MarkdownRenderer";
import { CalendarDeleteSection } from "./CalendarDeleteSection";
import { CalendarEditSection } from "./CalendarEditSection";
import CalendarEventSection from "./CalendarEventSection";
import CodeExecutionSection from "./CodeExecutionSection";
import ContactListSection from "./ContactListSection";
import DocumentSection from "./DocumentSection";
import EmailComposeSection from "./EmailComposeSection";
import EmailSentSection from "./EmailSentSection";
import GoogleDocsSection from "./GoogleDocsSection";
import GoalSection from "./goals/GoalSection";
import type { GoalAction } from "./goals/types";
import NotificationListSection from "./NotificationListSection";
import PeopleSearchSection from "./PeopleSearchSection";
import RedditCommentSection from "./RedditCommentSection";
import RedditCreatedSection from "./RedditCreatedSection";
import RedditPostSection from "./RedditPostSection";
import RedditSearchSection from "./RedditSearchSection";
import SupportTicketSection from "./SupportTicketSection";
import TodoSection from "./TodoSection";

// Map of tool_name -> renderer function for unified tool_data rendering
type RendererMap = {
  [K in ToolName]: (data: ToolDataMap[K], index: number) => React.ReactNode;
};
const TOOL_RENDERERS: Partial<RendererMap> = {
  // Search
  search_results: (data, index) => (
    <SearchResultsTabs
      key={`tool-search-${index}`}
      search_results={data as SearchResults}
    />
  ),
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
  email_fetch_data: (data, index) => (
    <EmailListCard
      key={`tool-email-fetch-${index}`}
      emails={(Array.isArray(data) ? data : [data]) as EmailFetchData[]}
    />
  ),
  email_compose_data: (data, index) => (
    <EmailComposeSection
      key={`tool-email-compose-${index}`}
      email_compose_data={
        (Array.isArray(data) ? data : [data]) as EmailComposeData[]
      }
    />
  ),
  email_sent_data: (data, index) => (
    <EmailSentSection
      key={`tool-email-sent-${index}`}
      email_sent_data={(Array.isArray(data) ? data : [data]) as EmailSentData[]}
    />
  ),
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
    return (
      <IntegrationConnectionPrompt
        key={`tool-integration-connection-${index}`}
        integration_connection_required={data as IntegrationConnectionData}
      />
    );
  },

  integration_list_data: (_data, index) => {
    return <IntegrationListSection key={`tool-integration-list-${index}`} />;
  },

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

export default function TextBubble({
  text,
  disclaimer,
  tool_data,
  isConvoSystemGenerated,
  systemPurpose,
  loading,
}: ChatBubbleBotProps) {
  const baseId = useId();

  // Parse thinking content from text
  const parsedContent = React.useMemo(() => {
    return parseThinkingFromText(text?.toString() || "");
  }, [text]);

  const processedTools = React.useMemo(() => {
    const grouped = new Map<ToolName, ToolDataMap[ToolName][]>();
    const individual: ToolDataEntry[] = [];

    tool_data?.forEach((entry) => {
      const toolName = entry.tool_name as ToolName;
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

    return [...groupedEntries, ...individual];
  }, [tool_data]);

  return (
    <>
      {parsedContent.thinking && (
        <ThinkingBubble thinkingContent={parsedContent.thinking} />
      )}

      {processedTools.map((entry, index) => {
        const toolName = entry.tool_name as ToolName;
        const renderer = TOOL_RENDERERS[toolName];
        if (!renderer) return null;

        const typedData = getTypedData(entry as ToolDataUnion, toolName);
        if (!typedData) return null;

        return (
          <React.Fragment key={`${baseId}-tool-${toolName}}`}>
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
                const groupedClasses = isFirst
                  ? "imessage-grouped-first mb-1.5"
                  : isLast
                    ? "imessage-grouped-last"
                    : "imessage-grouped-middle mb-1.5";

                return (
                  <div
                    // biome-ignore lint/suspicious/noArrayIndexKey: array is stable
                    key={`${baseId}-text-part-${index}`}
                    className={`imessage-bubble imessage-from-them ${groupedClasses}`}
                  >
                    {renderBubbleContent(part, isLast)}
                  </div>
                );
              })}
            </div>
          );
        })()}
    </>
  );
}
