"use client";

import { Avatar } from "@heroui/avatar";
import { Skeleton } from "@heroui/skeleton";
import {
  Alert01Icon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Mail01Icon,
  ZapIcon,
} from "@icons";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { GridSection } from "@/features/chat/components/interface/sections/GridSection";
import DummyComposer from "@/features/landing/components/demo/DummyComposer";
import { useHomePage } from "@/hooks/useHomePage";

function DashboardComposer() {
  const router = useRouter();

  return (
    <div className="relative mb-10 w-full px-4 sm:w-1/2 sm:px-0">
      {/* Visual-only — inert so nothing is interactive */}
      <div
        className="pointer-events-none [&_.searchbar_container]:pt-0 px-4"
        inert
      >
        <DummyComposer
          hideIntegrationBanner
          fullWidth
          className="max-w-none mx-0 items-stretch"
        />
      </div>
      {/* Invisible overlay captures all clicks → navigate to chat */}
      <button
        type="button"
        className="absolute inset-0 z-10 w-full cursor-text border-0 bg-transparent p-0"
        onClick={() => router.push("/c")}
        aria-label="Start a conversation"
      />
    </div>
  );
}

interface DashboardSection {
  icon: ReactNode;
  count: number;
  label: string;
}

interface DashboardCounts {
  todaysMeetings: number;
  tasksDue: number;
  overdueTodosCount: number;
  unreadEmailsCount: number;
  activeWorkflows: number;
}

function buildDashboardSections({
  todaysMeetings,
  tasksDue,
  overdueTodosCount,
  unreadEmailsCount,
  activeWorkflows,
}: DashboardCounts): DashboardSection[] {
  const sections: DashboardSection[] = [];
  if (todaysMeetings > 0) {
    sections.push({
      icon: <Calendar03Icon className="w-7 h-7 text-blue-400" />,
      count: todaysMeetings,
      label: todaysMeetings === 1 ? "meeting" : "meetings",
    });
  }
  if (tasksDue > 0) {
    sections.push({
      icon: <CheckmarkCircle02Icon className="w-7 h-7 text-emerald-400" />,
      count: tasksDue,
      label: tasksDue === 1 ? "task due" : "tasks due",
    });
  }
  if (overdueTodosCount > 0) {
    sections.push({
      icon: <Alert01Icon className="w-7 h-7 text-red-500" />,
      count: overdueTodosCount,
      label: overdueTodosCount === 1 ? "overdue task" : "overdue tasks",
    });
  }
  if (unreadEmailsCount > 0) {
    sections.push({
      icon: <Mail01Icon className="w-7 h-7 text-sky-400" />,
      count: unreadEmailsCount,
      label: unreadEmailsCount === 1 ? "unread email" : "unread emails",
    });
  }
  if (activeWorkflows > 0) {
    sections.push({
      icon: <ZapIcon className="w-7 h-7 text-amber-500" />,
      count: activeWorkflows,
      label: activeWorkflows === 1 ? "workflow" : "workflows",
    });
  }
  return sections;
}

function SummaryItem({ icon, count, label }: DashboardSection) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {icon}
      <span className="font-medium text-white">{count}</span>
      <span>{label}</span>
    </span>
  );
}

function DashboardSummary({
  sections,
  hasTodayItems,
}: {
  sections: DashboardSection[];
  hasTodayItems: boolean;
}) {
  const firstLineSections = sections.slice(0, 2);
  const secondLineSections = sections.slice(2);

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-3xl text-zinc-500">
        <span>You have</span>
        {firstLineSections.map((section, index) => (
          <span key={section.label}>
            <SummaryItem {...section} />
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
              <SummaryItem {...section} />
              {index < secondLineSections.length - 1 && <span>,</span>}
              {index === secondLineSections.length - 2 && <span> and</span>}
              {index === secondLineSections.length - 1 && hasTodayItems && (
                <span> today.</span>
              )}
              {index === secondLineSections.length - 1 && !hasTodayItems && (
                <span>.</span>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function HomePage() {
  const {
    user,
    simpleGreeting,
    isLoading,
    hasData,
    hasTodayItems,
    counts,
    events,
    calendars,
    unreadEmails,
    workflows,
    isCalendarConnected,
    isGmailConnected,
    calendarConnectLabel,
    gmailConnectLabel,
    emailsLoading,
    fetchMoreEmails,
    hasMoreEmails,
    emailsFetchingMore,
  } = useHomePage();

  // Build sections array for display
  const sections = buildDashboardSections(counts);

  return (
    <div className="flex flex-col p-6 pt-0 min-h-screen h-fit overflow-y-scroll outline-none">
      <div className="flex flex-col p-3 mb-6 space-y-1">
        <div className="flex items-center gap-3 mb-5">
          <h2 className="text-4xl font-medium text-zinc-700">
            {simpleGreeting}
          </h2>
          <div className="flex items-center gap-2">
            {user?.profilePicture && (
              <Avatar
                src={user?.profilePicture}
                name={user?.name || "User"}
                size="sm"
                className="shrink-0 ml-1 hover:scale-120 rotate-6 transition"
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
          <DashboardSummary sections={sections} hasTodayItems={hasTodayItems} />
        ) : (
          <p className="text-lg text-zinc-400">
            Your day is clear — time to plan ahead!
          </p>
        )}
      </div>

      <DashboardComposer />

      <GridSection
        events={events}
        calendars={calendars}
        unreadEmails={unreadEmails}
        workflows={workflows}
        isCalendarConnected={isCalendarConnected}
        isGmailConnected={isGmailConnected}
        calendarConnectLabel={calendarConnectLabel}
        gmailConnectLabel={gmailConnectLabel}
        emailsLoading={emailsLoading}
        onLoadMoreEmails={fetchMoreEmails}
        hasMoreEmails={hasMoreEmails}
        emailsFetchingMore={emailsFetchingMore}
      />
    </div>
  );
}
