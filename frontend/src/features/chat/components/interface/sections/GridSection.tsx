"use client";

import { useRouter } from "next/navigation";
import UpcomingEventsView from "@/features/calendar/components/UpcomingEventsView";
import { useCalendarsQuery } from "@/features/calendar/hooks/useCalendarsQuery";
import { useUpcomingEventsQuery } from "@/features/calendar/hooks/useUpcomingEventsQuery";
import RecentConversationsView from "@/features/chat/components/RecentConversationsView";
import GoalsView from "@/features/goals/components/GoalsView";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import UnreadEmailsView from "@/features/mail/components/UnreadEmailsView";
import { useUnreadEmailsQuery } from "@/features/mail/hooks/useUnreadEmailsQuery";
import InboxTodosView from "@/features/todo/components/InboxTodosView";
import WorkflowListView from "@/features/workflows/components/WorkflowListView";
import { posthog } from "@/lib/posthog";

export const GridSection = () => {
  const router = useRouter();
  const { getIntegrationStatus, connectIntegration } = useIntegrations();

  // Check integration connection statuses
  const gmailStatus = getIntegrationStatus("gmail");
  const calendarStatus = getIntegrationStatus("google_calendar");
  const isGmailConnected = gmailStatus?.connected || false;
  const isCalendarConnected = calendarStatus?.connected || false;

  // React Query automatically executes these queries in parallel
  // Only execute if the respective integrations are connected
  const emailQuery = useUnreadEmailsQuery(20, { enabled: isGmailConnected });
  const calendarQuery = useUpcomingEventsQuery(20, {
    enabled: isCalendarConnected,
  });
  const calendarsQuery = useCalendarsQuery({
    enabled: isCalendarConnected,
  });

  // Extract data with fallbacks
  const emailData = emailQuery.data ?? [];
  const calendarEvents = calendarQuery.data ?? [];
  const calendars = calendarsQuery.data ?? [];

  // Individual loading states for granular control
  const emailLoading = emailQuery.isLoading;

  // Fetching states for refresh functionality
  const emailFetching = emailQuery.isFetching;
  const calendarFetching = calendarQuery.isFetching;

  // Transform errors to match expected format
  const errors = {
    email: emailQuery.error
      ? new Error(emailQuery.error.message || "Failed to load emails")
      : null,
    calendar: calendarQuery.error
      ? calendarQuery.error.message || "Failed to load events"
      : null,
  };

  // Handle connection flow
  const handleConnect = async (integrationId: string) => {
    posthog.capture("chat:grid_integration_connect_clicked", {
      integration_id: integrationId,
      source: "new_chat_grid",
    });

    try {
      await connectIntegration(integrationId);
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  // Handle refresh actions
  const handleEmailRefresh = () => {
    posthog.capture("chat:grid_email_refresh_clicked");
    emailQuery.refetch();
  };

  const handleCalendarRefresh = () => {
    posthog.capture("chat:grid_calendar_refresh_clicked");
    calendarQuery.refetch();
  };

  return (
    <div className="relative flex h-fit w-full snap-start flex-col items-center justify-center">
      <div className="mb-20 grid min-h-screen w-full max-w-7xl grid-cols-1 grid-rows-1  sm:grid-cols-2 sm:space-y-0">
        <UnreadEmailsView
          emails={emailData}
          isLoading={emailLoading}
          isFetching={emailFetching}
          error={errors.email}
          isConnected={isGmailConnected}
          onConnect={handleConnect}
          onRefresh={handleEmailRefresh}
        />
        <UpcomingEventsView
          events={calendarEvents}
          isFetching={calendarFetching}
          error={errors.calendar}
          calendars={calendars}
          isConnected={isCalendarConnected}
          onConnect={handleConnect}
          onRefresh={handleCalendarRefresh}
          onEventClick={(_event) => {
            router.push("/calendar");
          }}
        />
        <InboxTodosView />
        <GoalsView />
        <WorkflowListView />
        <RecentConversationsView />
      </div>
    </div>
  );
};
