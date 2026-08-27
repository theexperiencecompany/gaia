import type {
  ApprovalRequestData,
  ArtifactData,
  CodeData,
  RateLimitData,
  RedditData,
  SearchResults,
  TodoProgressData,
  TwitterSearchData,
  TwitterUserData,
  WeatherData,
  WorkflowCreatedData,
  WorkflowDraftData,
} from "@gaia/shared";
import { Card } from "heroui-native";
import React from "react";
import { View } from "react-native";
import { Brain02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

import { ApprovalRequestCard } from "../components/chat/approval-request-card";
import { EmailComposeCard } from "../components/chat/email-compose-card";
import { ToolCardHeader, ToolCardShell } from "./primitives";
import type { EmailComposeData, ToolDataEntry } from "./registry";
import {
  ArtifactCard,
  CalendarDeleteCard,
  type CalendarDeleteOption,
  CalendarEditCard,
  type CalendarEditOption,
  CalendarFetchCard,
  type CalendarFetchItem,
  CalendarListFetchCard,
  type CalendarListFetchItem,
  type CalendarOption,
  CalendarOptionsCard,
  CodeExecutionCard,
  ConnectionStatusCard,
  type ConnectionStatusData,
  type ContactData,
  ContactListCard,
  DeepResearchCard,
  type DeepResearchResults,
  EmailFetchCard,
  type EmailFetchItem,
  EmailSentCard,
  EmailThreadCard,
  type EmailThreadData,
  GoogleDocsCard,
  type GoogleDocsData,
  IntegrationConnectionCard,
  type IntegrationConnectionData,
  IntegrationListCard,
  type IntegrationListData,
  MCPAppCard,
  NotificationCard,
  type NotificationData,
  PeopleSearchCard,
  type PeopleSearchData,
  RateLimitCard,
  RedditCard,
  SearchResultsCard,
  SupportTicketCard,
  type SupportTicketData,
  TodoCard,
  type TodoData,
  TodoProgressCard,
  TwitterSearchCard,
  TwitterUserCard,
  WeatherCard,
  WorkflowCreatedCard,
  WorkflowDraftCard,
} from "./tool-cards";

function UnsupportedToolCard({
  toolName,
  index,
}: {
  toolName: string;
  index: number;
}) {
  const displayName = toolName
    .replace(/_data$/, "")
    .replace(/_options$/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (l) => l.toUpperCase());

  return (
    <Card
      key={`unsupported-${toolName}-${index}`}
      variant="secondary"
      className="mx-4 my-2 rounded-xl"
    >
      <Card.Body className="py-3 px-4">
        <Text className="text-muted text-sm">{displayName} result</Text>
      </Card.Body>
    </Card>
  );
}

/** Content-derived list keys, de-duplicated with an occurrence suffix. */
function stableItemKeys<T>(items: T[], keyOf: (item: T) => string): string[] {
  const counts = new Map<string, number>();
  return items.map((item) => {
    const base = keyOf(item);
    const n = counts.get(base) ?? 0;
    counts.set(base, n + 1);
    return n === 0 ? base : `${base}-${n}`;
  });
}

const TOOL_RENDERERS: Record<
  string,
  (data: unknown, baseKey: string) => React.ReactNode
> = {
  email_compose_data: (data, baseKey) => {
    const emails = (Array.isArray(data) ? data : [data]) as EmailComposeData[];
    const keys = stableItemKeys(
      emails,
      (email) => email.subject || email.to?.join("-") || "draft",
    );
    return (
      <React.Fragment key={baseKey}>
        {emails.map((email, index) => (
          <EmailComposeCard key={keys[index]} data={email} />
        ))}
      </React.Fragment>
    );
  },

  email_sent_data: (data, baseKey) => {
    const emails = Array.isArray(data) ? data : [data];
    const keys = stableItemKeys(
      emails,
      (email) => email.message_id || email.subject || "sent",
    );
    return (
      <React.Fragment key={baseKey}>
        {emails.map((email, index) => (
          <EmailSentCard key={keys[index]} data={email} />
        ))}
      </React.Fragment>
    );
  },

  email_thread_data: (data, baseKey) => (
    <EmailThreadCard key={baseKey} data={data as EmailThreadData} />
  ),

  email_fetch_data: (data, baseKey) => {
    const emails = Array.isArray(data) ? data : [data];
    return <EmailFetchCard key={baseKey} data={emails as EmailFetchItem[]} />;
  },

  calendar_options: (data, baseKey) => {
    const events = Array.isArray(data) ? data : [data];
    return (
      <CalendarOptionsCard key={baseKey} data={events as CalendarOption[]} />
    );
  },

  calendar_fetch_data: (data, baseKey) => {
    const events = Array.isArray(data) ? data : [data];
    return (
      <CalendarFetchCard key={baseKey} data={events as CalendarFetchItem[]} />
    );
  },

  calendar_delete_options: (data, baseKey) => {
    const events = Array.isArray(data) ? data : [data];
    return (
      <CalendarDeleteCard
        key={baseKey}
        data={events as CalendarDeleteOption[]}
      />
    );
  },

  calendar_edit_options: (data, baseKey) => {
    const events = Array.isArray(data) ? data : [data];
    return (
      <CalendarEditCard key={baseKey} data={events as CalendarEditOption[]} />
    );
  },

  calendar_list_fetch_data: (data, baseKey) => {
    const calendars = Array.isArray(data) ? data : [data];
    return (
      <CalendarListFetchCard
        key={baseKey}
        data={calendars as CalendarListFetchItem[]}
      />
    );
  },

  weather_data: (data, baseKey) => (
    <WeatherCard key={baseKey} data={data as WeatherData} />
  ),

  search_results: (data, baseKey) => (
    <SearchResultsCard key={baseKey} data={data as SearchResults} />
  ),

  deep_research_results: (data, baseKey) => (
    <DeepResearchCard key={baseKey} data={data as DeepResearchResults} />
  ),

  contacts_data: (data, baseKey) => {
    const contacts = Array.isArray(data) ? data : [data];
    return <ContactListCard key={baseKey} data={contacts as ContactData[]} />;
  },

  people_search_data: (data, baseKey) => {
    const people = Array.isArray(data) ? data : [data];
    return (
      <PeopleSearchCard key={baseKey} data={people as PeopleSearchData[]} />
    );
  },

  support_ticket_data: (data, baseKey) => {
    const tickets = Array.isArray(data) ? data : [data];
    const keys = stableItemKeys(
      tickets,
      (ticket) => ticket.title || ticket.type || "ticket",
    );
    return (
      <React.Fragment key={baseKey}>
        {tickets.map((ticket, index) => (
          <SupportTicketCard
            key={keys[index]}
            data={ticket as SupportTicketData}
          />
        ))}
      </React.Fragment>
    );
  },

  notification_data: (data, baseKey) => (
    <NotificationCard key={baseKey} data={data as NotificationData} />
  ),

  todo_data: (data, baseKey) => (
    <TodoCard key={baseKey} data={data as TodoData} />
  ),

  google_docs_data: (data, baseKey) => (
    <GoogleDocsCard key={baseKey} data={data as GoogleDocsData} />
  ),

  code_data: (data, baseKey) => (
    <CodeExecutionCard key={baseKey} data={data as CodeData} />
  ),

  integration_connection_required: (data, baseKey) => (
    <IntegrationConnectionCard
      key={baseKey}
      data={data as IntegrationConnectionData}
    />
  ),

  integration_list_data: (data, baseKey) => {
    // Backend may stream grouped data (array) — merge into one list
    const items = Array.isArray(data)
      ? (data as IntegrationListData[])
      : [data as IntegrationListData];
    const merged: IntegrationListData = items.reduce<IntegrationListData>(
      (acc, item) => ({
        hasSuggestions: acc.hasSuggestions || item.hasSuggestions,
        message: acc.message ?? item.message,
        suggested: [...(acc.suggested ?? []), ...(item.suggested ?? [])],
        integrations: [
          ...(acc.integrations ?? []),
          ...(item.integrations ?? []),
        ],
      }),
      {},
    );
    return <IntegrationListCard key={baseKey} data={merged} />;
  },

  twitter_search_data: (data, baseKey) => (
    <TwitterSearchCard key={baseKey} data={data as TwitterSearchData} />
  ),

  twitter_user_data: (data, baseKey) => {
    const users = Array.isArray(data) ? data : [data];
    return <TwitterUserCard key={baseKey} data={users as TwitterUserData[]} />;
  },

  workflow_draft: (data, baseKey) => (
    <WorkflowDraftCard key={baseKey} data={data as WorkflowDraftData} />
  ),

  workflow_created: (data, baseKey) => (
    <WorkflowCreatedCard key={baseKey} data={data as WorkflowCreatedData} />
  ),

  connection_status_data: (data, baseKey) => (
    <ConnectionStatusCard key={baseKey} data={data as ConnectionStatusData} />
  ),

  rate_limit_data: (data, baseKey) => (
    <RateLimitCard key={baseKey} data={data as RateLimitData} />
  ),

  artifact_data: (data, baseKey) => {
    const files = Array.isArray(data) ? data : [data];
    return <ArtifactCard key={baseKey} data={files as ArtifactData[]} />;
  },

  reddit_data: (data, baseKey) => {
    const items = Array.isArray(data) ? data : [data];
    const keys = stableItemKeys(
      items,
      (item) => item.type || item.post?.title || "post",
    );
    return (
      <React.Fragment key={baseKey}>
        {items.map((item, index) => (
          <RedditCard key={keys[index]} data={item as RedditData} />
        ))}
      </React.Fragment>
    );
  },

  memory_data: (data, baseKey) => {
    const mem = data as Record<string, unknown> | null;
    const count =
      mem && typeof mem.count === "number" && mem.count > 0
        ? mem.count
        : undefined;
    return (
      <ToolCardShell key={baseKey}>
        <ToolCardHeader
          icon={Brain02Icon}
          iconColor="#a78bfa"
          title="Memory updated"
          count={count}
        />
      </ToolCardShell>
    );
  },

  // mcp_app: rendered via MCPAppCard — shows a notice that interactive
  // rendering is web-only while keeping the result in conversation context.
  mcp_app: (data, baseKey) => <MCPAppCard key={baseKey} data={data} />,

  todo_progress: (data, baseKey) => (
    <TodoProgressCard
      key={baseKey}
      data={data as TodoProgressData}
      isStreaming
    />
  ),

  // HIL approval — pending→resolved updates replace it in place via
  // upsertApprovalToolData (shared turn accumulator / use-chat onToolData).
  approval_request: (data, baseKey) => (
    <ApprovalRequestCard key={baseKey} data={data as ApprovalRequestData} />
  ),
};

interface ToolDataRendererProps {
  toolData?: ToolDataEntry[];
}

export function ToolDataRenderer({ toolData }: ToolDataRendererProps) {
  if (!toolData || toolData.length === 0) {
    return null;
  }

  return (
    <View className="flex-col w-full">
      {toolData.map((entry, index) => {
        const toolName = entry.tool_name;
        const renderer = TOOL_RENDERERS[toolName];
        const baseKey = `tool-${toolName}-${entry.timestamp || index}`;

        if (renderer) {
          return (
            <React.Fragment key={baseKey}>
              {renderer(entry.data, baseKey)}
            </React.Fragment>
          );
        }

        return (
          <UnsupportedToolCard
            key={baseKey}
            toolName={toolName}
            index={index}
          />
        );
      })}
    </View>
  );
}

export { TOOL_RENDERERS };
