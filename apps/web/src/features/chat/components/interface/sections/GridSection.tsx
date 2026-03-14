"use client";

import { useRouter } from "next/navigation";
import UpcomingEventsView from "@/features/calendar/components/UpcomingEventsView";
import RecentConversationsView from "@/features/chat/components/RecentConversationsView";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import UnreadEmailsView from "@/features/mail/components/UnreadEmailsView";
import InboxTodosView from "@/features/todo/components/InboxTodosView";
import WorkflowListView from "@/features/workflows/components/WorkflowListView";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import type { CalendarItem } from "@/types/api/calendarApiTypes";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";
import type { EmailData } from "@/types/features/mailTypes";
import type { Workflow } from "@/types/features/workflowTypes";

interface GridSectionProps {
  events?: GoogleCalendarEvent[];
  calendars?: CalendarItem[];
  unreadEmails?: EmailData[];
  workflows?: Workflow[];
  isCalendarConnected: boolean;
  isGmailConnected: boolean;
  emailsLoading?: boolean;
  onLoadMoreEmails?: () => void;
  hasMoreEmails?: boolean;
  emailsFetchingMore?: boolean;
}

export const GridSection = ({
  events = [],
  calendars = [],
  unreadEmails = [],
  workflows = [],
  isCalendarConnected,
  isGmailConnected,
  emailsLoading = false,
  onLoadMoreEmails,
  hasMoreEmails,
  emailsFetchingMore,
}: GridSectionProps) => {
  const router = useRouter();
  const { connectIntegration } = useIntegrations();

  const handleConnect = async (integrationId: string) => {
    trackEvent(ANALYTICS_EVENTS.CHAT_GRID_INTEGRATION_CONNECT_CLICKED, {
      integration_id: integrationId,
      source: "new_chat_grid",
    });

    try {
      await connectIntegration(integrationId);
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  return (
    <div className="relative flex h-fit w-full snap-start flex-col items-center justify-center">
      <div className="mb-20 grid min-h-screen w-full grid-cols-1 grid-rows-1  sm:grid-cols-2 sm:space-y-0">
        <UnreadEmailsView
          emails={unreadEmails}
          isConnected={isGmailConnected}
          onConnect={handleConnect}
          isFetching={emailsLoading}
          onLoadMore={onLoadMoreEmails}
          hasNextPage={hasMoreEmails}
          isFetchingNextPage={emailsFetchingMore}
        />
        <UpcomingEventsView
          events={events}
          calendars={calendars}
          isConnected={isCalendarConnected}
          onConnect={handleConnect}
          onEventClick={(_event) => {
            router.push("/calendar");
          }}
        />
        <InboxTodosView />
        <WorkflowListView workflows={workflows} />
        <RecentConversationsView />
      </div>
    </div>
  );
};
