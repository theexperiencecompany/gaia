import { Card } from "heroui-native";
import React from "react";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

import { EmailComposeCard } from "../components/chat/email-compose-card";
import type { EmailComposeData, ToolDataEntry } from "./registry";
import {
  ArtifactCard,
  CalendarDeleteCard,
  type CalendarDeleteOption,
  CalendarEditCard,
  type CalendarEditOption,
  CalendarFetchCard,
  type CalendarFetchItem,
  type CalendarOption,
  CalendarOptionsCard,
  type CodeData,
  CodeExecutionCard,
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
  MCPAppCard,
  NotificationCard,
  type NotificationData,
  PeopleSearchCard,
  type PeopleSearchData,
  RateLimitCard,
  RedditCard,
  type RedditData,
  type SearchResults,
  SearchResultsCard,
  SupportTicketCard,
  type SupportTicketData,
  TodoCard,
  type TodoData,
  ToolCallsCard,
  TwitterSearchCard,
  TwitterUsersCard,
  WeatherCard,
  type WeatherData,
  WorkflowCreatedCard,
  WorkflowDraftCard,
} from "./tool-cards";

const GROUPED_TOOLS = new Set<string>([
  "search_results",
  "reddit_data",
  "tool_calls_data",
  "integration_connection_required",
  "integration_list_data",
  "rate_limit_data",
  "email_fetch_data",
  "email_compose_data",
  "email_sent_data",
  "artifact_data",
  "twitter_user_data",
]);

const flattenOneLevel = (value: unknown): unknown[] => {
  if (!Array.isArray(value)) return [value];
  return value.flat(1);
};

const dedupeToolCalls = (calls: unknown[]): unknown[] => {
  const seen = new Set<string>();
  return calls.filter((call) => {
    if (typeof call !== "object" || call === null) return true;
    const toolCallId = (call as { tool_call_id?: string }).tool_call_id;
    if (!toolCallId) return true;
    if (seen.has(toolCallId)) return false;
    seen.add(toolCallId);
    return true;
  });
};

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
      <CalendarFetchCard
        key={baseKey}
        data={calendars as CalendarFetchItem[]}
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
    const source = Array.isArray(data) ? data[0] : data;
    const suggested =
      source && typeof source === "object" && "suggested" in source
        ? ((source as { suggested?: unknown[] }).suggested ?? [])
        : [];

    return (
      <Card key={baseKey} variant="secondary" className="mx-4 my-2 rounded-xl">
        <Card.Body className="py-3 px-4">
          <Text className="text-foreground text-sm">
            Suggested Integrations
          </Text>
          <Text className="text-xs text-muted mt-1">
            {suggested.length > 0
              ? `${suggested.length} suggestion${suggested.length > 1 ? "s" : ""}`
              : "Open /integrations to connect tools"}
          </Text>
        </Card.Body>
      </Card>
    );
  },

  tool_calls_data: (data, baseKey) => (
    <ToolCallsCard key={baseKey} data={data} />
  ),

  twitter_search_data: (data, baseKey) => (
    <TwitterSearchCard key={baseKey} data={data} />
  ),

  twitter_user_data: (data, baseKey) => (
    <TwitterUsersCard key={baseKey} data={data} />
  ),

  workflow_draft: (data, baseKey) => (
    <WorkflowDraftCard key={baseKey} data={data} />
  ),

  workflow_created: (data, baseKey) => (
    <WorkflowCreatedCard key={baseKey} data={data} />
  ),

  mcp_app: (data, baseKey) => <MCPAppCard key={baseKey} data={data} />,

  rate_limit_data: (data, baseKey) => (
    <RateLimitCard key={baseKey} data={data} />
  ),

  artifact_data: (data, baseKey) => <ArtifactCard key={baseKey} data={data} />,

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

  memory_data: (_data, baseKey) => (
    <Card key={baseKey} variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="py-3 px-4">
        <Text className="text-xs text-muted mb-1">Memory</Text>
        <Text className="text-foreground text-sm">Memory updated</Text>
      </Card.Body>
    </Card>
  ),

  todo_progress: (data, baseKey) => {
    const progress = data as Record<
      string,
      {
        todos?: { id: string; content: string; status: string }[];
        source?: string;
      }
    >;
    const allTodos: {
      id: string;
      content: string;
      status: string;
      source: string;
    }[] = [];
    for (const [source, snapshot] of Object.entries(progress)) {
      if (snapshot?.todos) {
        for (const todo of snapshot.todos) {
          allTodos.push({ ...todo, source });
        }
      }
    }
    if (allTodos.length === 0) return null;
    const completedCount = allTodos.filter(
      (t) => t.status === "completed",
    ).length;
    const completionPct = Math.round((completedCount / allTodos.length) * 100);
    const statusIcon: Record<string, string> = {
      completed: "\u2713",
      in_progress: "\u2192",
      cancelled: "\u2717",
      pending: "\u25CB",
    };
    return (
      <Card key={baseKey} variant="secondary" className="mx-4 my-2 rounded-xl">
        <Card.Body className="py-3 px-4">
          <View className="flex-row items-center justify-between mb-1.5">
            <Text className="text-xs text-muted">Task Progress</Text>
            <Text className="text-xs text-muted">
              {completedCount}/{allTodos.length}
            </Text>
          </View>
          <View className="h-1.5 rounded-full bg-muted/30 mb-2">
            <View
              className="h-1.5 rounded-full bg-primary"
              style={{ width: `${completionPct}%` }}
            />
          </View>
          <Text className="text-[10px] text-muted mb-2">
            {completionPct}% complete • {Object.keys(progress).length} source
            {Object.keys(progress).length > 1 ? "s" : ""}
          </Text>
          {allTodos.map((todo) => (
            <View
              key={`${todo.source}-${todo.id}`}
              className="flex-row items-start gap-2 mb-1"
            >
              <Text className="text-xs text-muted w-4">
                {statusIcon[todo.status] ?? "\u25CB"}
              </Text>
              <Text
                className={`text-xs flex-1 ${todo.status === "completed" ? "text-success" : todo.status === "in_progress" ? "text-primary" : "text-muted"}`}
              >
                {todo.content}
              </Text>
            </View>
          ))}
        </Card.Body>
      </Card>
    );
  },
};

interface ToolDataRendererProps {
  toolData?: ToolDataEntry[];
}

export function ToolDataRenderer({ toolData }: ToolDataRendererProps) {
  if (!toolData || toolData.length === 0) {
    return null;
  }

  const grouped = new Map<string, unknown[]>();
  const individual: ToolDataEntry[] = [];

  for (const entry of toolData) {
    if (GROUPED_TOOLS.has(entry.tool_name)) {
      if (!grouped.has(entry.tool_name)) {
        grouped.set(entry.tool_name, []);
      }
      grouped.get(entry.tool_name)?.push(entry.data);
      continue;
    }

    individual.push(entry);
  }

  const groupedEntries: ToolDataEntry[] = Array.from(grouped.entries()).map(
    ([toolName, dataArray]) => {
      const flattened = flattenOneLevel(dataArray);
      const normalizedData =
        toolName === "tool_calls_data" ? dedupeToolCalls(flattened) : flattened;

      return {
        tool_name: toolName,
        data: normalizedData,
        timestamp: null,
      };
    },
  );

  const processedToolData = [...groupedEntries, ...individual];

  return (
    <View className="flex-col">
      {processedToolData.map((entry, index) => {
        const toolName = entry.tool_name;
        const renderer = TOOL_RENDERERS[toolName];
        const baseKey = `tool-${toolName}-${entry.timestamp || index}`;

        if (renderer) {
          return renderer(entry.data, baseKey);
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
