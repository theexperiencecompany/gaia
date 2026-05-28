"use client";

import { TOOL_FIXTURES, type ToolFixture } from "@shared/chat";
import { useParams } from "next/navigation";
import type { JSX } from "react";
import ErrorBoundary from "@/components/shared/ErrorBoundary";
import CalendarListCard from "@/features/calendar/components/CalendarListCard";
import CalendarListFetchCard from "@/features/calendar/components/CalendarListFetchCard";
import { CalendarDeleteSection } from "@/features/chat/components/bubbles/bot/CalendarDeleteSection";
import { CalendarEditSection } from "@/features/chat/components/bubbles/bot/CalendarEditSection";
import CalendarEventSection from "@/features/chat/components/bubbles/bot/CalendarEventSection";
import CodeExecutionSection from "@/features/chat/components/bubbles/bot/CodeExecutionSection";
import ContactListSection from "@/features/chat/components/bubbles/bot/ContactListSection";
import DeepResearchResultsTabs from "@/features/chat/components/bubbles/bot/DeepResearchResultsTabs";
import DocumentSection from "@/features/chat/components/bubbles/bot/DocumentSection";
import EmailComposeSection from "@/features/chat/components/bubbles/bot/EmailComposeSection";
import EmailSentSection from "@/features/chat/components/bubbles/bot/EmailSentSection";
import EmailThreadCard from "@/features/chat/components/bubbles/bot/EmailThreadCard";
import FileArtifactSection from "@/features/chat/components/bubbles/bot/FileArtifactSection";
import GoogleDocsSection from "@/features/chat/components/bubbles/bot/GoogleDocsSection";
import GoalSection from "@/features/chat/components/bubbles/bot/goals/GoalSection";
import IntegrationConnectionPrompt from "@/features/chat/components/bubbles/bot/IntegrationConnectionPrompt";
import NotificationListSection from "@/features/chat/components/bubbles/bot/NotificationListSection";
import PeopleSearchSection from "@/features/chat/components/bubbles/bot/PeopleSearchSection";
import RateLimitCard from "@/features/chat/components/bubbles/bot/RateLimitCard";
import RedditCommentSection from "@/features/chat/components/bubbles/bot/RedditCommentSection";
import RedditPostSection from "@/features/chat/components/bubbles/bot/RedditPostSection";
import RedditSearchSection from "@/features/chat/components/bubbles/bot/RedditSearchSection";
import SearchResultsTabs from "@/features/chat/components/bubbles/bot/SearchResultsTabs";
import SupportTicketSection from "@/features/chat/components/bubbles/bot/SupportTicketSection";
import TodoProgressSection from "@/features/chat/components/bubbles/bot/TodoProgressSection";
import TodoSection from "@/features/chat/components/bubbles/bot/TodoSection";
import TwitterSearchSection from "@/features/chat/components/bubbles/bot/TwitterSearchSection";
import TwitterUserSection from "@/features/chat/components/bubbles/bot/TwitterUserSection";
import { MCPAppRenderer } from "@/features/chat/components/tools/MCPAppRenderer";
import { IntegrationListSection } from "@/features/integrations/components/IntegrationListSection";
import EmailListCard from "@/features/mail/components/EmailListCard";
import { WeatherCard } from "@/features/weather/components/WeatherCard";
import WorkflowCreatedCard from "@/features/workflows/components/WorkflowCreatedCard";
import WorkflowDraftCard from "@/features/workflows/components/WorkflowDraftCard";

function UnsupportedOnWeb({ label }: { label: string }): JSX.Element {
  return (
    <div className="rounded-2xl bg-zinc-900 p-3 text-sm text-zinc-500">
      No web renderer for{" "}
      <span className="font-mono text-zinc-400">{label}</span>
    </div>
  );
}

function GalleryRenderer({ fixture }: { fixture: ToolFixture }): JSX.Element {
  const { toolName, data } = fixture;

  switch (toolName) {
    case "weather_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <WeatherCard weatherData={data as any} />;
    case "search_results":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <SearchResultsTabs search_results={data as any} />;
    case "deep_research_results":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <DeepResearchResultsTabs deep_research_results={data as any} />;
    case "email_fetch_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <EmailListCard emails={data as any} />;
    case "email_thread_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <EmailThreadCard emailThreadData={data as any} />;
    case "email_compose_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <EmailComposeSection email_compose_data={data as any} />;
    case "email_sent_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <EmailSentSection email_sent_data={data as any} />;
    case "contacts_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <ContactListSection contacts_data={data as any} />;
    case "people_search_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <PeopleSearchSection people_search_data={data as any} />;
    case "calendar_options":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <CalendarEventSection calendar_options={data as any} />;
    case "calendar_delete_options":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <CalendarDeleteSection calendar_delete_options={data as any} />;
    case "calendar_edit_options":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <CalendarEditSection calendar_edit_options={data as any} />;
    case "calendar_fetch_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <CalendarListCard events={data as any} />;
    case "calendar_list_fetch_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <CalendarListFetchCard calendars={data as any} />;
    case "todo_data": {
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      const d = data as any;
      return (
        <TodoSection
          todos={d.todos}
          projects={d.projects}
          stats={d.stats}
          action={d.action}
          message={d.message}
        />
      );
    }
    case "todo_progress":
      return (
        // biome-ignore lint/suspicious/noExplicitAny: gallery-only
        <TodoProgressSection todo_progress={data as any} />
      );
    case "goal_data": {
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      const g = data as any;
      return (
        <GoalSection
          goals={g.goals}
          stats={g.stats}
          action={g.action}
          message={g.message}
        />
      );
    }
    case "document_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <DocumentSection document_data={data as any} />;
    case "google_docs_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <GoogleDocsSection google_docs_data={data as any} />;
    case "code_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <CodeExecutionSection code_data={data as any} />;
    case "artifact_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <FileArtifactSection artifact_data={data as any} />;
    case "twitter_search_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <TwitterSearchSection twitter_search_data={data as any} />;
    case "twitter_user_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <TwitterUserSection twitter_user_data={data as any} />;
    case "reddit_data": {
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      const d = data as any;
      if (d.type === "search") {
        return <RedditSearchSection reddit_search_data={d.posts} />;
      }
      if (d.type === "post") {
        return <RedditPostSection reddit_post_data={d.post} />;
      }
      if (d.type === "comments") {
        return <RedditCommentSection reddit_comment_data={d.comments} />;
      }
      return <UnsupportedOnWeb label="Reddit (unknown variant)" />;
    }
    case "integration_connection_required":
      return (
        <IntegrationConnectionPrompt
          // biome-ignore lint/suspicious/noExplicitAny: gallery-only
          integration_connection_required={data as any}
        />
      );
    case "integration_list_data": {
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      const d = data as any;
      return (
        <IntegrationListSection suggestedIntegrations={d.suggested ?? []} />
      );
    }
    case "workflow_draft":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <WorkflowDraftCard draft={data as any} />;
    case "workflow_created":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <WorkflowCreatedCard workflow={data as any} />;
    case "support_ticket_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <SupportTicketSection support_ticket_data={data as any} />;
    case "notification_data": {
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      const d = data as any;
      return (
        <NotificationListSection
          notifications={d.notifications ?? []}
          title="Your Notifications"
        />
      );
    }
    case "rate_limit_data":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <RateLimitCard data={data as any} />;
    case "mcp_app":
      // biome-ignore lint/suspicious/noExplicitAny: gallery-only
      return <MCPAppRenderer data={data as any} />;
    case "memory_data":
    case "connection_status_data":
    case "chart_data":
      return <UnsupportedOnWeb label={toolName} />;
    default:
      return <UnsupportedOnWeb label={String(toolName)} />;
  }
}

export default function ToolPage(): JSX.Element {
  const params = useParams();
  const toolName = params?.tool as string;
  const fixture = TOOL_FIXTURES.find((f) => f.toolName === toolName);

  if (!fixture) {
    return (
      <div className="flex-1 overflow-y-auto px-8 py-8">
        <p className="text-sm text-zinc-500">
          Unknown tool:{" "}
          <span className="font-mono text-zinc-400">{toolName}</span>
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-8 py-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-zinc-100">{fixture.label}</h1>
        <p className="mt-1 text-xs text-zinc-500">
          <span className="font-mono">{fixture.toolName}</span>
          {" · "}
          {fixture.description}
        </p>
      </div>
      <ErrorBoundary>
        <GalleryRenderer fixture={fixture} />
      </ErrorBoundary>
    </div>
  );
}
