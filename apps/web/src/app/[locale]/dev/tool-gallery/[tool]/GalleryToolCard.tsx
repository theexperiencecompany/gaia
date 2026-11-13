import type { ToolFixture } from "@shared/chat";
import type { JSX } from "react";
import type { ToolDataMap, ToolName } from "@/config/registries/toolRegistry";
import CalendarListCard from "@/features/calendar/components/CalendarListCard";
import { CalendarDeleteSection } from "@/features/chat/components/bubbles/bot/CalendarDeleteSection";
import { CalendarEditSection } from "@/features/chat/components/bubbles/bot/CalendarEditSection";
import CodeExecutionSection from "@/features/chat/components/bubbles/bot/CodeExecutionSection";
import ContactListSection from "@/features/chat/components/bubbles/bot/ContactListSection";
import DeepResearchResultsTabs from "@/features/chat/components/bubbles/bot/DeepResearchResultsTabs";
import EmailComposeSection from "@/features/chat/components/bubbles/bot/EmailComposeSection";
import EmailSentSection from "@/features/chat/components/bubbles/bot/EmailSentSection";
import EmailThreadCard from "@/features/chat/components/bubbles/bot/EmailThreadCard";
import FileArtifactSection from "@/features/chat/components/bubbles/bot/FileArtifactSection";
import GoogleDocsSection from "@/features/chat/components/bubbles/bot/GoogleDocsSection";
import IntegrationConnectionPrompt from "@/features/chat/components/bubbles/bot/IntegrationConnectionPrompt";
import NotificationListSection from "@/features/chat/components/bubbles/bot/NotificationListSection";
import PeopleSearchSection from "@/features/chat/components/bubbles/bot/PeopleSearchSection";
import RateLimitCard from "@/features/chat/components/bubbles/bot/RateLimitCard";
import RedditCommentSection from "@/features/chat/components/bubbles/bot/RedditCommentSection";
import RedditPostSection from "@/features/chat/components/bubbles/bot/RedditPostSection";
import RedditSearchSection from "@/features/chat/components/bubbles/bot/RedditSearchSection";
import SearchResultsTabs from "@/features/chat/components/bubbles/bot/SearchResultsTabs";
import SendNotificationSection from "@/features/chat/components/bubbles/bot/SendNotificationSection";
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
import type { RedditData } from "@/types/features/redditTypes";

type GalleryRenderers = {
  [K in ToolName]?: (data: ToolDataMap[K]) => JSX.Element;
};

function UnsupportedOnWeb({ label }: { label: string }): JSX.Element {
  return (
    <div className="rounded-2xl bg-zinc-900 p-3 text-sm text-zinc-500">
      No web renderer for{" "}
      <span className="font-mono text-zinc-400">{label}</span>
    </div>
  );
}

function renderRedditFixture(data: RedditData): JSX.Element {
  switch (data.type) {
    case "search":
      return <RedditSearchSection reddit_search_data={data.posts} />;
    case "post":
      return <RedditPostSection reddit_post_data={data.post} />;
    case "comments":
      return <RedditCommentSection reddit_comment_data={data.comments} />;
    default:
      return <UnsupportedOnWeb label="Reddit (unknown variant)" />;
  }
}

// Fixtures render their raw payload, not the grouped/merged shape the chat
// stream hands TOOL_RENDERERS, so this map is the gallery's own.
const GALLERY_RENDERERS: GalleryRenderers = {
  weather_data: (data) => <WeatherCard weatherData={data} />,
  search_results: (data) => <SearchResultsTabs search_results={data} />,
  deep_research_results: (data) => (
    <DeepResearchResultsTabs deep_research_results={data} />
  ),
  email_fetch_data: (data) => <EmailListCard emails={data} />,
  email_thread_data: (data) => <EmailThreadCard emailThreadData={data} />,
  email_compose_data: (data) => (
    <EmailComposeSection email_compose_data={data} />
  ),
  email_sent_data: (data) => <EmailSentSection email_sent_data={data} />,
  contacts_data: (data) => <ContactListSection contacts_data={data} />,
  people_search_data: (data) => (
    <PeopleSearchSection people_search_data={data} />
  ),
  calendar_delete_options: (data) => (
    <CalendarDeleteSection calendar_delete_options={data} />
  ),
  calendar_edit_options: (data) => (
    <CalendarEditSection calendar_edit_options={data} />
  ),
  calendar_fetch_data: (data) => <CalendarListCard events={data} />,
  todo_data: (data) => (
    <TodoSection
      todos={data.todos}
      projects={data.projects}
      stats={data.stats}
      action={data.action}
      message={data.message}
    />
  ),
  todo_progress: (data) => <TodoProgressSection todo_progress={data} />,
  google_docs_data: (data) => <GoogleDocsSection google_docs_data={data} />,
  code_data: (data) => <CodeExecutionSection code_data={data} />,
  artifact_data: (data) => <FileArtifactSection artifact_data={data} />,
  twitter_search_data: (data) => (
    <TwitterSearchSection twitter_search_data={data} />
  ),
  twitter_user_data: (data) => <TwitterUserSection twitter_user_data={data} />,
  reddit_data: renderRedditFixture,
  integration_connection_required: (data) => (
    <IntegrationConnectionPrompt integration_connection_required={data} />
  ),
  integration_list_data: (data) => (
    <IntegrationListSection suggestedIntegrations={data.suggested ?? []} />
  ),
  workflow_draft: (data) => <WorkflowDraftCard draft={data} />,
  workflow_created: (data) => <WorkflowCreatedCard workflow={data} />,
  support_ticket_data: (data) => (
    <SupportTicketSection support_ticket_data={data} />
  ),
  notification_data: (data) => (
    <NotificationListSection
      notifications={data.notifications ?? []}
      title="Your Notifications"
    />
  ),
  send_notification_data: (data) => (
    <SendNotificationSection send_notification_data={data} />
  ),
  rate_limit_data: (data) => <RateLimitCard data={data} />,
  mcp_app: (data) => <MCPAppRenderer data={data} />,
};

function hasGalleryCard(toolName: string): toolName is ToolName {
  return Object.hasOwn(GALLERY_RENDERERS, toolName);
}

function renderGalleryCard<K extends ToolName>(
  toolName: K,
  data: ToolDataMap[K],
): JSX.Element | undefined {
  return GALLERY_RENDERERS[toolName]?.(data);
}

/** A fixture's card, or a notice naming the tool when the web has no card for it. */
export default function GalleryToolCard({
  fixture,
}: {
  fixture: ToolFixture;
}): JSX.Element {
  const { toolName, data } = fixture;
  const card = hasGalleryCard(toolName)
    ? renderGalleryCard(toolName, data as ToolDataMap[typeof toolName])
    : undefined;
  return card ?? <UnsupportedOnWeb label={toolName} />;
}
