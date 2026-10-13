"use client";

import {
  CONNECT_ACTION_LABEL,
  getSimpleTimeGreeting,
  integrationConnectionState,
} from "@shared/utils";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { useCalendarsQuery } from "@/features/calendar/hooks/useCalendarsQuery";
import { useUpcomingEventsQuery } from "@/features/calendar/hooks/useUpcomingEventsQuery";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useUnreadEmailsQuery } from "@/features/mail/hooks/useUnreadEmailsQuery";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import { useWorkflows } from "@/features/workflows/hooks/useWorkflows";

export function useHomePage() {
  const user = useCurrentUser();
  const { counts: todoCounts, loading: todosLoading } = useTodoData();
  const { getIntegrationStatus } = useIntegrations();

  // Check integrations. The state (not just the boolean) drives the CTA verb, so
  // an integration whose grant died offers Reconnect instead of a first-time Connect.
  const calendarState = integrationConnectionState(
    getIntegrationStatus("googlecalendar")?.status,
  );
  const gmailState = integrationConnectionState(
    getIntegrationStatus("gmail")?.status,
  );
  const isCalendarConnected = calendarState === "connected";
  const isGmailConnected = gmailState === "connected";

  const { data: events, isLoading: eventsLoading } = useUpcomingEventsQuery(
    50,
    {
      enabled: isCalendarConnected,
    },
  );
  const { data: calendars, isLoading: calendarsLoading } = useCalendarsQuery({
    enabled: isCalendarConnected,
  });
  const {
    data: unreadEmailsData,
    isLoading: emailsLoading,
    fetchNextPage: fetchMoreEmails,
    hasNextPage: hasMoreEmails,
    isFetchingNextPage: emailsFetchingMore,
  } = useUnreadEmailsQuery(10, { enabled: isGmailConnected });
  const unreadEmails = unreadEmailsData?.pages.flatMap((p) => p.messages) ?? [];
  const { workflows, isLoading: workflowsLoading } = useWorkflows(true);

  // Calculate today's data
  const today = new Date().toDateString();
  const todaysMeetings =
    events?.filter((e) => {
      const startDate = e.start.dateTime || e.start.date;
      if (!startDate) return false;
      const eventDate = new Date(startDate);
      return eventDate.toDateString() === today;
    }).length || 0;

  // Filter active workflows and calculate counts
  const activeWorkflows =
    workflows?.filter((w) => w.activated === true).length || 0;
  const tasksDue = todoCounts?.today || 0;
  const overdueTodosCount = todoCounts?.overdue || 0;
  const unreadEmailsCount = unreadEmails?.length || 0;

  const simpleGreeting = getSimpleTimeGreeting();
  const isLoading =
    todosLoading ||
    eventsLoading ||
    calendarsLoading ||
    workflowsLoading ||
    emailsLoading;

  // Only show "today" if there are actual time-bound items (meetings or tasks due today)
  const hasTodayItems = todaysMeetings > 0 || tasksDue > 0;
  const hasData =
    hasTodayItems ||
    overdueTodosCount > 0 ||
    unreadEmailsCount > 0 ||
    activeWorkflows > 0;

  return {
    user,
    simpleGreeting,
    isLoading,
    hasData,
    hasTodayItems,
    counts: {
      todaysMeetings,
      tasksDue,
      overdueTodosCount,
      unreadEmailsCount,
      activeWorkflows,
    },
    events,
    calendars,
    unreadEmails,
    workflows,
    isCalendarConnected,
    isGmailConnected,
    calendarConnectLabel: CONNECT_ACTION_LABEL[calendarState],
    gmailConnectLabel: CONNECT_ACTION_LABEL[gmailState],
    emailsLoading,
    fetchMoreEmails,
    hasMoreEmails,
    emailsFetchingMore,
  };
}
