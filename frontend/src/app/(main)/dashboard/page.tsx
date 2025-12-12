"use client";

import { Avatar } from "@heroui/avatar";
import { Skeleton } from "@heroui/skeleton";
import { useEffect } from "react";
import { useUser } from "@/features/auth/hooks/useUser";
import { useCalendarsQuery } from "@/features/calendar/hooks/useCalendarsQuery";
import { useUpcomingEventsQuery } from "@/features/calendar/hooks/useUpcomingEventsQuery";
import { GridSection } from "@/features/chat/components/interface";
import { useGoals } from "@/features/goals/hooks/useGoals";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useUnreadEmailsQuery } from "@/features/mail/hooks/useUnreadEmailsQuery";
import { useTodoData } from "@/features/todo/hooks/useTodoData";
import { useWorkflows } from "@/features/workflows/hooks/useWorkflows";
import {
  Alert01Icon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Mail01Icon,
  Target02Icon,
  ZapIcon,
} from "@/icons";
import {
  getSimpleTimeGreeting,
  getTimeBasedGreeting,
} from "@/utils/greetingUtils";

export default function HomePage() {
  const user = useUser();
  const { counts: todoCounts, loading: todosLoading } = useTodoData();
  const { goals, loading: goalsLoading, fetchGoals } = useGoals();
  const { getIntegrationStatus } = useIntegrations();

  // Check integrations
  const calendarStatus = getIntegrationStatus("google_calendar");
  const isCalendarConnected = calendarStatus?.connected || false;
  const gmailStatus = getIntegrationStatus("gmail");
  const isGmailConnected = gmailStatus?.connected || false;

  const { data: events, isLoading: eventsLoading } = useUpcomingEventsQuery(
    50,
    {
      enabled: isCalendarConnected,
    },
  );
  const { data: calendars, isLoading: calendarsLoading } = useCalendarsQuery({
    enabled: isCalendarConnected,
  });
  const { data: unreadEmails, isLoading: emailsLoading } = useUnreadEmailsQuery(
    100,
    {
      enabled: isGmailConnected,
    },
  );
  const { workflows, isLoading: workflowsLoading } = useWorkflows(true);

  // Fetch goals on mount
  useEffect(() => {
    fetchGoals();
  }, [fetchGoals]);

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
  const totalGoals = goals?.length || 0;
  const unreadEmailsCount = unreadEmails?.length || 0;

  const simpleGreeting = getSimpleTimeGreeting();
  const isLoading =
    todosLoading ||
    eventsLoading ||
    calendarsLoading ||
    workflowsLoading ||
    goalsLoading ||
    emailsLoading;

  // Only show "today" if there are actual time-bound items (meetings or tasks due today)
  // Overdue tasks, emails, workflows, and goals are NOT "today" items
  const hasTodayItems = todaysMeetings > 0 || tasksDue > 0;
  const hasData =
    hasTodayItems ||
    overdueTodosCount > 0 ||
    unreadEmailsCount > 0 ||
    activeWorkflows > 0 ||
    totalGoals > 0;

  // Build sections array for display
  const sections = [];
  if (todaysMeetings > 0) {
    sections.push({
      icon: <Calendar03Icon className="w-7 h-7 text-blue-400" />,
      count: todaysMeetings,
      label: todaysMeetings === 1 ? "meeting" : "meetings",
    });
  }
  if (tasksDue > 0) {
    sections.push({
      icon: <CheckmarkCircle02Icon className="w-7 h-7 text-green-400" />,
      count: tasksDue,
      label: tasksDue === 1 ? "task due" : "tasks due",
    });
  }
  if (overdueTodosCount > 0) {
    sections.push({
      icon: <Alert01Icon className="w-7 h-7 text-red-400" />,
      count: overdueTodosCount,
      label: overdueTodosCount === 1 ? "overdue task" : "overdue tasks",
    });
  }
  if (unreadEmailsCount > 0) {
    sections.push({
      icon: <Mail01Icon className="w-7 h-7 text-cyan-400" />,
      count: unreadEmailsCount,
      label: unreadEmailsCount === 1 ? "unread email" : "unread emails",
    });
  }
  if (activeWorkflows > 0) {
    sections.push({
      icon: <ZapIcon className="w-7 h-7 text-purple-400" />,
      count: activeWorkflows,
      label: activeWorkflows === 1 ? "workflow" : "workflows",
    });
  }
  if (totalGoals > 0) {
    sections.push({
      icon: <Target02Icon className="w-7 h-7 text-orange-400" />,
      count: totalGoals,
      label: totalGoals === 1 ? "goal" : "goals",
    });
  }

  const firstLineSections = sections.slice(0, 2);
  const secondLineSections = sections.slice(2);

  return (
    <div className="flex flex-col p-6 min-h-screen h-fit overflow-y-scroll">
      <div className="flex flex-col p-3 mb-10 space-y-1">
        <div className="flex items-center gap-3 mb-9">
          <h2 className="text-4xl font-medium text-zinc-700">
            {simpleGreeting}
          </h2>
          <div className="flex items-center gap-2">
            {user?.profilePicture && (
              <Avatar
                src={user?.profilePicture}
                name={user?.name || "User"}
                size="sm"
                className="flex-shrink-0 ml-1 hover:scale-120 rotate-6 transition"
              />
            )}
            <h1 className="font-medium text-4xl text-zinc-700">
              {user?.name?.split(" ")[0]}
              <span className="ml-4">:)</span>
            </h1>
          </div>
        </div>

        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-7 w-[30vw] rounded-lg" />
            <Skeleton className="h-7 w-[50vw] rounded-lg" />
          </div>
        ) : hasData ? (
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-3xl text-zinc-500">
              <span>You have</span>
              {firstLineSections.map((section, index) => (
                <span key={section.label}>
                  <span className="inline-flex items-center gap-1.5">
                    {section.icon}
                    <span className="font-medium text-white">
                      {section.count}
                    </span>
                    <span>{section.label}</span>
                  </span>
                  {index < firstLineSections.length - 1 && <span>,</span>}
                  {index === firstLineSections.length - 1 &&
                    secondLineSections.length === 0 &&
                    hasTodayItems && <span> today</span>}
                  {index === firstLineSections.length - 1 &&
                    secondLineSections.length === 0 &&
                    !hasTodayItems && <span>.</span>}
                  {index === firstLineSections.length - 1 &&
                    secondLineSections.length > 0 && <span>,</span>}
                </span>
              ))}
            </div>

            {secondLineSections.length > 0 && (
              <div className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-3xl text-zinc-500">
                {secondLineSections.map((section, index) => (
                  <span key={section.label}>
                    <span className="inline-flex items-center gap-1.5">
                      {section.icon}
                      <span className="font-medium text-white">
                        {section.count}
                      </span>
                      <span>{section.label}</span>
                    </span>
                    {index < secondLineSections.length - 1 && <span>,</span>}
                    {index === secondLineSections.length - 2 && (
                      <span> and</span>
                    )}
                    {index === secondLineSections.length - 1 &&
                      hasTodayItems && <span> today.</span>}
                    {index === secondLineSections.length - 1 &&
                      !hasTodayItems && <span>.</span>}
                  </span>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="text-lg text-zinc-400">
            Your day is clear — time to plan ahead!
          </p>
        )}
      </div>
      <GridSection
        events={events}
        calendars={calendars}
        unreadEmails={unreadEmails}
        workflows={workflows}
        goals={goals}
        isCalendarConnected={isCalendarConnected}
        isGmailConnected={isGmailConnected}
      />
    </div>
  );
}
