import type {
  CodeData,
  RedditData,
  SearchResults,
  TodoProgressData,
  WeatherData,
} from "@gaia/shared";
import { Card, PressableFeedback } from "heroui-native";
import React, { useCallback, useRef, useState } from "react";
import { Animated, LayoutAnimation, View } from "react-native";
import { AppIcon, ArrowDown02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

import { EmailComposeCard } from "../components/chat/email-compose-card";
import type { EmailComposeData, ToolDataEntry } from "./registry";
import {
  CalendarDeleteCard,
  type CalendarDeleteOption,
  CalendarEditCard,
  type CalendarEditOption,
  CalendarFetchCard,
  type CalendarFetchItem,
  type CalendarOption,
  CalendarOptionsCard,
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
  NotificationCard,
  type NotificationData,
  PeopleSearchCard,
  type PeopleSearchData,
  RedditCard,
  SearchResultsCard,
  SupportTicketCard,
  type SupportTicketData,
  TodoCard,
  type TodoData,
  TodoProgressCard,
  WeatherCard,
} from "./tool-cards";

function getToolDisplayName(toolName: string): string {
  return toolName
    .replace(/_data$/, "")
    .replace(/_options$/, "")
    .replace(/_results$/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (l) => l.toUpperCase());
}

function CollapsibleToolWrapper({
  toolName,
  children,
}: {
  toolName: string;
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const chevronAnim = useRef(new Animated.Value(0)).current;
  const { spacing, fontSize, moderateScale } = useResponsive();

  const toggle = useCallback(() => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setCollapsed((prev) => {
      const next = !prev;
      Animated.timing(chevronAnim, {
        toValue: next ? 1 : 0,
        duration: 200,
        useNativeDriver: true,
      }).start();
      return next;
    });
  }, [chevronAnim]);

  const chevronRotate = chevronAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "-90deg"],
  });

  const displayName = getToolDisplayName(toolName);

  return (
    <View style={{ marginBottom: spacing.xs }}>
      <PressableFeedback
        onPress={toggle}
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.xs + 2,
          gap: spacing.xs,
        }}
      >
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#52525b",
            fontWeight: "500",
            flex: 1,
          }}
        >
          {displayName}
        </Text>
        <Animated.View style={{ transform: [{ rotate: chevronRotate }] }}>
          <AppIcon
            icon={ArrowDown02Icon}
            size={moderateScale(12, 0.5)}
            color="#52525b"
          />
        </Animated.View>
      </PressableFeedback>
      {!collapsed && children}
    </View>
  );
}

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

  integration_list_data: (_data, baseKey) => (
    <Card key={baseKey} variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="py-3 px-4">
        <Text className="text-foreground text-sm">Available Integrations</Text>
      </Card.Body>
    </Card>
  ),

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

  todo_progress: (data, baseKey) => (
    <TodoProgressCard
      key={baseKey}
      data={data as TodoProgressData}
      isStreaming
    />
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
    <View className="flex-col">
      {toolData.map((entry, index) => {
        const toolName = entry.tool_name;
        const renderer = TOOL_RENDERERS[toolName];
        const baseKey = `tool-${toolName}-${entry.timestamp || index}`;

        const rendered = renderer ? (
          renderer(entry.data, baseKey)
        ) : (
          <UnsupportedToolCard
            key={baseKey}
            toolName={toolName}
            index={index}
          />
        );

        return (
          <CollapsibleToolWrapper key={baseKey} toolName={toolName}>
            {rendered}
          </CollapsibleToolWrapper>
        );
      })}
    </View>
  );
}

export { TOOL_RENDERERS };
