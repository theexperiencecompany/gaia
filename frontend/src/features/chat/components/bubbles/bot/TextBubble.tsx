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
import { AlertTriangleIcon } from "lucide-react";
import React from "react";

// import { PostHogCaptureOnViewed } from "posthog-js/react";
import { ToolDataMap, ToolName } from "@/config/registries/toolRegistry";
import CalendarListCard from "@/features/calendar/components/CalendarListCard";
import CalendarListFetchCard from "@/features/calendar/components/CalendarListFetchCard";
import DeepResearchResultsTabs from "@/features/chat/components/bubbles/bot/DeepResearchResultsTabs";
import EmailThreadCard from "@/features/chat/components/bubbles/bot/EmailThreadCard";
import IntegrationConnectionPrompt from "@/features/chat/components/bubbles/bot/IntegrationConnectionPrompt";
import SearchResultsTabs from "@/features/chat/components/bubbles/bot/SearchResultsTabs";
import { splitMessageByBreaks } from "@/features/chat/utils/messageBreakUtils";
import { shouldShowTextBubble } from "@/features/chat/utils/messageContentUtils";
import EmailListCard from "@/features/mail/components/EmailListCard";
import { WeatherCard } from "@/features/weather/components/WeatherCard";
import {
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
import {
  CalendarFetchData,
  CalendarListFetchData,
} from "@/types/features/calendarTypes";
import { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import {
  ContactData,
  EmailFetchData,
  PeopleSearchData,
} from "@/types/features/mailTypes";
import { NotificationRecord } from "@/types/features/notificationTypes";
import { SupportTicketData } from "@/types/features/supportTypes";

import MarkdownRenderer from "../../interface/MarkdownRenderer";
import { CalendarDeleteSection } from "./CalendarDeleteSection";
import { CalendarEditSection } from "./CalendarEditSection";
import CalendarEventSection from "./CalendarEventSection";
import CodeExecutionSection from "./CodeExecutionSection";
import ContactListSection from "./ContactListSection";
import DocumentSection from "./DocumentSection";
import EmailComposeSection from "./EmailComposeSection";
import EmailSentSection from "./EmailSentSection";
import GoalSection from "./goals/GoalSection";
import { GoalAction } from "./goals/types";
import GoogleDocsSection from "./GoogleDocsSection";
import NotificationListSection from "./NotificationListSection";
import PeopleSearchSection from "./PeopleSearchSection";
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
        integration_connection_required={
          data as {
            integration_id: string;
            message: string;
          }
        }
      />
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
  integration_connection_required,
  isConvoSystemGenerated,
  systemPurpose,
}: ChatBubbleBotProps) {
  return (
    <>
      {integration_connection_required && (
        <IntegrationConnectionPrompt
          integration_connection_required={integration_connection_required}
        />
      )}

      {/* Unified tool_data rendering via registry */}
      {tool_data?.map((entry, index) => {
        const toolName = entry.tool_name as ToolName;

        if (!TOOL_RENDERERS[toolName]) return null;
        // Use type guard to get the correct type for data
        const typedData = getTypedData(entry as ToolDataUnion, toolName);
        if (typedData === undefined) return null;

        return (
          <React.Fragment key={`tool-${toolName}-${index}`}>
            {renderTool(toolName, typedData, index)}
            {/*
            <PostHogCaptureOnViewed >
            {/* </PostHogCaptureOnViewed> */}
          </React.Fragment>
        );
      })}

      {shouldShowTextBubble(text, isConvoSystemGenerated, systemPurpose) &&
        (() => {
          const textParts = splitMessageByBreaks(text?.toString() || "");
          const hasMultipleParts = textParts.length > 1;

          const renderBubbleContent = (
            content: string,
            showDisclaimer: boolean,
          ) => (
            <div className="flex flex-col gap-3">
              <MarkdownRenderer content={content} />
              {!!disclaimer && showDisclaimer && (
                <Chip
                  className="text-xs font-medium text-warning-500"
                  color="warning"
                  size="sm"
                  startContent={
                    <AlertTriangleIcon
                      className="text-warning-500"
                      height={17}
                    />
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
                    key={index}
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
