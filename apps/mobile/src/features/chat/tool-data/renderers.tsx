import { Card } from "heroui-native";
import React from "react";
import { View } from "react-native";
import { AppIcon, Brain02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { EmailComposeCard } from "../components/chat/email-compose-card";
import type { ToolCallEntry } from "../components/chat/tool-calls-section";
import { ToolCallsSection } from "../components/chat/tool-calls-section";
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
  ChartCard,
  type ChartDisplayData,
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
  TodoProgressCard,
  type TodoProgressData,
  TwitterSearchCard,
  TwitterUsersCard,
  WeatherCard,
  type WeatherData,
  WorkflowCreatedCard,
  WorkflowDraftCard,
} from "./tool-cards";

function MemoryBrainIcon({ size = 12 }: { size?: number }) {
  return <AppIcon icon={Brain02Icon} size={size} color="#818cf8" />;
}

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
  "chart_data",
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
      <Card
        key={baseKey}
        variant="secondary"
        className="mx-4 my-2 rounded-2xl bg-[#171920]"
      >
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

  tool_calls_data: (data, baseKey) => {
    const calls = (
      Array.isArray(data) ? (data as unknown[]).flat(1) : [data]
    ) as ToolCallEntry[];
    return (
      <View key={baseKey} style={{ paddingHorizontal: 16, paddingVertical: 4 }}>
        <ToolCallsSection tool_calls_data={calls} />
      </View>
    );
  },

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

  memory_data: (data, baseKey) => {
    const mem = data as {
      type?: string;
      operation?: string;
      status?: string;
      count?: number;
      content?: string;
    } | null;

    let label = "Memory updated";
    let detail: string | null = null;

    if (mem) {
      if (mem.type === "memory_stored") {
        label = "Memory stored";
        if (mem.content) detail = mem.content;
      } else if (mem.status === "success") {
        switch (mem.operation) {
          case "create":
            label = "Memory created";
            if (mem.content) detail = mem.content;
            break;
          case "search":
            label =
              mem.count === 0
                ? "No memories found"
                : mem.count === 1
                  ? "Found 1 memory"
                  : `Found ${mem.count} memories`;
            break;
          case "list":
            label =
              mem.count === 0
                ? "No memories"
                : `Retrieved ${mem.count} memories`;
            break;
          default:
            label = "Memory operation completed";
        }
      } else if (mem.status === "storing") {
        label = "Storing memory...";
      } else if (mem.status === "searching") {
        label = "Searching memories...";
      } else if (mem.status === "retrieving") {
        label = "Retrieving memories...";
      }
    }

    return (
      <Card
        key={baseKey}
        variant="secondary"
        className="mx-4 my-2 rounded-2xl bg-[#171920]"
      >
        <Card.Body className="py-3 px-4">
          <View className="flex-row items-center gap-2">
            <View className="rounded-full bg-indigo-500/20 p-1">
              <MemoryBrainIcon size={12} />
            </View>
            <Text className="text-xs text-muted">Memory</Text>
          </View>
          <Text className="text-foreground text-sm font-medium mt-1.5">
            {label}
          </Text>
          {!!detail && (
            <Text className="text-xs text-muted mt-1" numberOfLines={3}>
              {detail}
            </Text>
          )}
        </Card.Body>
      </Card>
    );
  },

  todo_progress: (data, baseKey) => (
    <TodoProgressCard key={baseKey} data={data as TodoProgressData} />
  ),

  chart_data: (data, baseKey) => {
    const charts = (Array.isArray(data) ? data : [data]) as ChartDisplayData[];
    return <ChartCard key={baseKey} data={charts} />;
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
