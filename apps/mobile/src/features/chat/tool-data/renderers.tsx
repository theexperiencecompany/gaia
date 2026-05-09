import type {
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

import { EmailComposeCard } from "../components/chat/email-compose-card";
import {
  type ToolCallEntry,
  ToolCallsSection,
} from "../components/chat/tool-calls-section";
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
  DocumentCard,
  type DocumentData,
  EmailFetchCard,
  type EmailFetchItem,
  EmailSentCard,
  EmailThreadCard,
  type EmailThreadData,
  GoalCard,
  type GoalData,
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

const TOOL_RENDERERS: Record<
  string,
  (data: unknown, baseKey: string) => React.ReactNode
> = {
  email_compose_data: (data, baseKey) => {
    const emails = (Array.isArray(data) ? data : [data]) as EmailComposeData[];
    return (
      <React.Fragment key={baseKey}>
        {emails.map((email) => (
          <EmailComposeCard
            key={`${baseKey}-${email.subject || email.to?.join("-") || Math.random()}`}
            data={email}
          />
        ))}
      </React.Fragment>
    );
  },

  email_sent_data: (data, baseKey) => {
    const emails = Array.isArray(data) ? data : [data];
    return (
      <React.Fragment key={baseKey}>
        {emails.map((email) => (
          <EmailSentCard
            key={`${baseKey}-${email.message_id || email.subject || Math.random()}`}
            data={email}
          />
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
    return (
      <React.Fragment key={baseKey}>
        {tickets.map((ticket) => (
          <SupportTicketCard
            key={`${baseKey}-${ticket.title || ticket.type || Math.random()}`}
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

  goal_data: (data, baseKey) => (
    <GoalCard key={baseKey} data={data as GoalData} />
  ),

  document_data: (data, baseKey) => (
    <DocumentCard key={baseKey} data={data as DocumentData} />
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
    return (
      <React.Fragment key={baseKey}>
        {items.map((item) => (
          <RedditCard
            key={`${baseKey}-${item.type || item.post?.title || Math.random()}`}
            data={item as RedditData}
          />
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

  // Stacked tool-icons + "Used N tools" collapsible (matches web parity).
  // Backend may stream this as a single object that should be wrapped, or
  // as an already-built array.
  tool_calls_data: (data, baseKey) => {
    const calls = (Array.isArray(data) ? data : [data]) as ToolCallEntry[];
    return <ToolCallsSection key={baseKey} tool_calls_data={calls} />;
  },
};

interface ToolDataRendererProps {
  toolData?: ToolDataEntry[];
}

/**
 * Backend streams `tool_calls_data` as one entry per call, but the UI
 * should render a single consolidated "Used N tools" section per message
 * (mirrors apps/web/src/features/chat/components/interface/ChatRenderer.tsx
 * which dedupes by tool_call_id and merges into one entry). Without this,
 * multiple "Used 1 tool" headers stack on top of each other.
 */
function consolidateToolData(toolData: ToolDataEntry[]): ToolDataEntry[] {
  const result: ToolDataEntry[] = [];
  let toolCallsBuffer: Record<string, unknown>[] = [];
  let firstToolCallsTimestamp: ToolDataEntry["timestamp"] | undefined;
  // tool_call_id → index inside toolCallsBuffer, so a later streamed entry
  // (e.g. carrying `output` once execution finishes) can be merged into the
  // earlier entry instead of being dropped as a duplicate.
  const idToIndex = new Map<string, number>();

  const flush = () => {
    if (toolCallsBuffer.length > 0) {
      result.push({
        tool_name: "tool_calls_data",
        data: toolCallsBuffer,
        timestamp: firstToolCallsTimestamp,
      });
      toolCallsBuffer = [];
      firstToolCallsTimestamp = undefined;
    }
  };

  for (const entry of toolData) {
    if (entry.tool_name === "tool_calls_data") {
      const calls = Array.isArray(entry.data) ? entry.data : [entry.data];
      for (const rawCall of calls) {
        const call = (rawCall ?? {}) as Record<string, unknown>;
        const id =
          typeof call.tool_call_id === "string" ? call.tool_call_id : undefined;

        if (id && idToIndex.has(id)) {
          // Merge new fields onto the existing entry. Prefer the latest
          // non-empty value for fields that grow over time (status, output,
          // message). Inputs typically stream complete on the first event,
          // but we still merge to be defensive.
          const existingIndex = idToIndex.get(id) as number;
          const existing = toolCallsBuffer[existingIndex] ?? {};
          toolCallsBuffer[existingIndex] = {
            ...existing,
            ...Object.fromEntries(
              Object.entries(call).filter(
                ([, v]) => v !== undefined && v !== "",
              ),
            ),
          };
          continue;
        }

        if (id) idToIndex.set(id, toolCallsBuffer.length);
        toolCallsBuffer.push(call);
      }
      if (firstToolCallsTimestamp === undefined) {
        firstToolCallsTimestamp = entry.timestamp;
      }
    } else {
      flush();
      result.push(entry);
    }
  }
  flush();
  return result;
}

export function ToolDataRenderer({ toolData }: ToolDataRendererProps) {
  if (!toolData || toolData.length === 0) {
    return null;
  }

  const consolidated = consolidateToolData(toolData);

  return (
    <View className="flex-col w-full">
      {consolidated.map((entry, index) => {
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
