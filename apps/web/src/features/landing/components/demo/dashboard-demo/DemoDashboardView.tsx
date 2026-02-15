"use client";

import { Chip } from "@heroui/chip";
import { ScrollShadow } from "@heroui/scroll-shadow";
import {
  Alert01Icon,
  Calendar03Icon,
  CalendarUpload01Icon,
  CheckmarkCircle02Icon,
  InboxUnreadIcon,
  Mail01Icon,
  MessageMultiple02Icon,
  Target02Icon,
  WorkflowSquare05Icon,
  ZapIcon,
} from "@icons";
import { m, useInView } from "motion/react";
import { useRef } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  DUMMY_CALENDARS,
  DUMMY_CONVERSATIONS,
  DUMMY_EMAILS,
  DUMMY_EVENTS,
  DUMMY_GOALS,
  DUMMY_TODOS,
  DUMMY_WORKFLOWS,
} from "./dashboardDemoConstants";

function DemoBaseCard({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-full w-full flex-col rounded-3xl">
      <div className="flex flex-shrink-0 items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="font-medium text-zinc-300">{title}</h3>
        </div>
      </div>
      <div className="h-full flex-1 px-4 pb-4">
        <div className="h-full max-h-[40vh] min-h-[40vh] w-full overflow-y-auto rounded-2xl bg-zinc-900/80">
          {children}
        </div>
      </div>
    </div>
  );
}

function DemoEmailsCard() {
  return (
    <DemoBaseCard
      title="Unread emails"
      icon={<InboxUnreadIcon className="h-6 w-6 text-zinc-500" />}
    >
      <ScrollShadow className="h-full">
        {DUMMY_EMAILS.map((email) => {
          const fromName = email.from.split("<")[0].trim();
          const timeAgo = getRelativeTime(email.time);
          return (
            <div
              key={email.id}
              className="flex cursor-pointer items-start gap-3 border-b border-zinc-800/50 px-4 py-3 transition-colors hover:bg-zinc-800/50"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-zinc-200 truncate">
                    {fromName}
                  </span>
                  <span className="text-xs text-zinc-500 shrink-0">
                    {timeAgo}
                  </span>
                </div>
                <p className="mt-0.5 text-sm text-zinc-400 line-clamp-1">
                  {email.subject}
                </p>
              </div>
            </div>
          );
        })}
      </ScrollShadow>
    </DemoBaseCard>
  );
}

function DemoEventsCard() {
  const eventsByDay: Record<string, typeof DUMMY_EVENTS> = {};
  for (const event of DUMMY_EVENTS) {
    const dateStr =
      event.start.dateTime?.slice(0, 10) ||
      new Date().toISOString().slice(0, 10);
    if (!eventsByDay[dateStr]) eventsByDay[dateStr] = [];
    eventsByDay[dateStr].push(event);
  }

  return (
    <DemoBaseCard
      title="Upcoming events"
      icon={<CalendarUpload01Icon className="h-6 w-6 text-zinc-500" />}
    >
      <div className="space-y-6 p-4">
        {Object.entries(eventsByDay).map(([dateString, events], index) => {
          const date = new Date(`${dateString}T12:00:00`);
          const isToday = date.toDateString() === new Date().toDateString();
          const label = isToday
            ? "Today"
            : date.toLocaleDateString("en-US", {
                weekday: "short",
                month: "short",
                day: "numeric",
              });

          return (
            <div key={dateString} className="flex gap-4">
              <div className="w-1/5 flex-shrink-0">
                <div className="sticky top-0 z-10 px-2 pt-1">
                  <span
                    className={`text-sm ${index === 0 ? "text-primary" : "text-zinc-400"}`}
                  >
                    {label}
                  </span>
                </div>
              </div>
              <div className="flex-1 space-y-2">
                {events.map((event) => {
                  const color =
                    DUMMY_CALENDARS.find((c) => c.id === event.calendarId)
                      ?.backgroundColor || "#00bbff";
                  const startTime = formatEventTime(
                    event.start.dateTime || "",
                    event.end.dateTime || "",
                  );

                  return (
                    <div
                      key={event.id}
                      className="relative flex cursor-pointer items-start gap-2 rounded-lg p-2 pl-5 transition-colors hover:bg-zinc-700/30"
                      style={{ backgroundColor: `${color}10` }}
                    >
                      <div className="absolute top-0 left-1 flex h-full items-center">
                        <div
                          className="mt-0.5 h-[80%] w-1 flex-shrink-0 rounded-full"
                          style={{ backgroundColor: color }}
                        />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-base leading-tight font-medium text-white">
                          {event.summary}
                        </div>
                        <div className="mt-0.5 text-xs text-zinc-400">
                          {startTime}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </DemoBaseCard>
  );
}

function DemoTodosCard() {
  const priorityColors: Record<string, string> = {
    high: "border-red-500",
    medium: "border-yellow-500",
    low: "border-blue-500",
  };

  return (
    <DemoBaseCard
      title="Inbox Todos"
      icon={<CheckmarkCircle02Icon className="h-6 w-6 text-zinc-500" />}
    >
      <div className="space-y-0">
        {DUMMY_TODOS.map((todo) => (
          <div
            key={todo.id}
            className="flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors hover:bg-zinc-700/30"
          >
            <div
              className={`mt-1 h-4 w-4 shrink-0 rounded-full border-2 border-dashed ${priorityColors[todo.priority] || "border-zinc-600"}`}
            />
            <div className="min-w-0 flex-1">
              <h4 className="text-sm font-medium text-white line-clamp-1">
                {todo.title}
              </h4>
              {todo.description && (
                <p className="mt-0.5 text-xs text-zinc-500 line-clamp-1">
                  {todo.description}
                </p>
              )}
              <div className="mt-1.5 flex flex-wrap items-center gap-1">
                <Chip
                  size="sm"
                  variant="flat"
                  className="text-zinc-400 px-1"
                  radius="sm"
                >
                  {todo.priority}
                </Chip>
                {todo.due_date && (
                  <Chip
                    size="sm"
                    variant="flat"
                    className="text-zinc-400 px-1"
                    radius="sm"
                  >
                    {new Date(todo.due_date).toDateString() ===
                    new Date().toDateString()
                      ? "Today"
                      : new Date(todo.due_date).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                        })}
                  </Chip>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </DemoBaseCard>
  );
}

function DemoWorkflowsCard() {
  return (
    <DemoBaseCard
      title="Workflows"
      icon={<WorkflowSquare05Icon className="h-6 w-6 text-zinc-500" />}
    >
      <div className="space-y-2 p-4">
        {DUMMY_WORKFLOWS.map((workflow) => {
          const categories = [
            ...new Set(workflow.steps.map((s) => s.category)),
          ];
          return (
            <div
              key={workflow.id}
              className="flex cursor-pointer items-center gap-3 rounded-2xl bg-zinc-800/50 p-3 transition-colors hover:bg-zinc-700/50"
            >
              <div className="relative flex h-10 shrink-0 items-center justify-center">
                <div className="flex min-h-8 items-center -space-x-1.5">
                  {categories.slice(0, 3).map((category, index) => (
                    <div
                      key={category}
                      className="relative flex min-w-8 items-center justify-center"
                      style={{
                        rotate:
                          categories.length > 1
                            ? index % 2 === 0
                              ? "8deg"
                              : "-8deg"
                            : "0deg",
                        zIndex: index,
                      }}
                    >
                      {getToolCategoryIcon(category, {
                        width: 24,
                        height: 24,
                      })}
                    </div>
                  ))}
                </div>
              </div>
              <div className="min-w-0 flex-1">
                <h4 className="font-medium text-white line-clamp-1">
                  {workflow.title}
                </h4>
                <p className="mt-0.5 text-xs text-zinc-400 line-clamp-1">
                  {workflow.description}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </DemoBaseCard>
  );
}

function DemoGoalsCard() {
  return (
    <DemoBaseCard
      title="Goals"
      icon={<Target02Icon className="h-6 w-6 text-zinc-500" />}
    >
      <div className="space-y-0">
        {DUMMY_GOALS.map((goal) => {
          const totalSteps = goal.roadmap?.nodes?.length || 0;
          const completedSteps =
            goal.roadmap?.nodes?.filter((n) => n.data?.isComplete).length || 0;
          const hasSteps = totalSteps > 0;

          return (
            <div
              key={goal.id}
              className="flex cursor-pointer items-start gap-3 p-4 transition-colors hover:bg-zinc-700/30"
            >
              <div className="min-w-0 flex-1">
                <h4 className="text-base font-medium text-white">
                  {goal.title}
                </h4>
                {goal.description && (
                  <p className="mt-1 text-xs text-zinc-400 line-clamp-2">
                    {goal.description}
                  </p>
                )}
                {hasSteps && (
                  <div className="mt-2 flex items-center gap-2">
                    <div className="relative h-2 flex-1 rounded-full">
                      <div
                        className="absolute top-0 left-0 z-[2] h-2 rounded-full bg-primary"
                        style={{ width: `${goal.progress}%` }}
                      />
                      <div className="absolute top-0 left-0 h-2 w-full rounded-full bg-zinc-900" />
                    </div>
                    <span className="text-xs text-zinc-400 min-w-[2.5rem]">
                      {goal.progress}%
                    </span>
                  </div>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-1">
                  <Chip
                    color={
                      goal.progress === 100
                        ? "success"
                        : goal.progress > 0
                          ? "primary"
                          : "warning"
                    }
                    size="sm"
                    variant="flat"
                  >
                    {goal.progress === 100
                      ? "Completed"
                      : goal.progress > 0
                        ? "In Progress"
                        : "Not Started"}
                  </Chip>
                  {hasSteps && (
                    <Chip
                      size="sm"
                      variant="flat"
                      className="text-zinc-400 px-1"
                      radius="sm"
                      startContent={
                        <CheckmarkCircle02Icon
                          width={15}
                          height={15}
                          className="mx-1"
                        />
                      }
                    >
                      {completedSteps}/{totalSteps} steps
                    </Chip>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </DemoBaseCard>
  );
}

function DemoConversationsCard() {
  return (
    <DemoBaseCard
      title="Recent Conversations"
      icon={<MessageMultiple02Icon className="h-6 w-6 text-zinc-500" />}
    >
      <div className="space-y-0">
        {DUMMY_CONVERSATIONS.map((conversation) => (
          <div
            key={conversation.conversation_id}
            className="flex cursor-pointer items-start gap-3 p-4 transition-colors hover:bg-zinc-700/30"
          >
            <div className="min-w-0 flex-1 flex justify-between">
              <div>
                <div className="flex items-start justify-between gap-2">
                  <h4 className="text-base font-medium text-white line-clamp-1">
                    {conversation.title}
                  </h4>
                  {conversation.starred && (
                    <span className="flex-shrink-0 text-yellow-500">★</span>
                  )}
                </div>
                {conversation.description && (
                  <p className="mt-1 text-xs text-zinc-400 line-clamp-2">
                    {conversation.description}
                  </p>
                )}
              </div>
              <div className="mt-2 flex items-center gap-1">
                <Chip
                  size="sm"
                  variant="flat"
                  className="text-zinc-400 px-1"
                  radius="sm"
                  startContent={
                    <MessageMultiple02Icon
                      width={15}
                      height={15}
                      className="mx-1"
                    />
                  }
                >
                  {conversation.messageCount}{" "}
                  {conversation.messageCount === 1 ? "message" : "messages"}
                </Chip>
                <Chip
                  size="sm"
                  variant="flat"
                  className="text-zinc-400 px-1"
                  radius="sm"
                  startContent={
                    <Calendar03Icon width={15} height={15} className="mx-1" />
                  }
                >
                  {new Date(conversation.updated_at).toLocaleDateString()}
                </Chip>
              </div>
            </div>
          </div>
        ))}
      </div>
    </DemoBaseCard>
  );
}

function getRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatEventTime(start: string, end: string): string {
  const s = new Date(start);
  const e = new Date(end);
  const fmt = (d: Date) => {
    const h = d.getHours();
    const m = d.getMinutes();
    const ampm = h >= 12 ? "PM" : "AM";
    const h12 = h % 12 || 12;
    return m === 0
      ? `${h12} ${ampm}`
      : `${h12}:${m.toString().padStart(2, "0")} ${ampm}`;
  };
  return `${fmt(s)} – ${fmt(e)}`;
}

export default function DemoDashboardView() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, amount: 0.15 });

  const sections = [
    {
      icon: <Calendar03Icon className="w-7 h-7 text-blue-400" />,
      count: 3,
      label: "meetings",
    },
    {
      icon: <CheckmarkCircle02Icon className="w-7 h-7 text-emerald-400" />,
      count: 4,
      label: "tasks due",
    },
    {
      icon: <Alert01Icon className="w-7 h-7 text-red-500" />,
      count: 1,
      label: "overdue task",
    },
    {
      icon: <Mail01Icon className="w-7 h-7 text-sky-400" />,
      count: 5,
      label: "unread emails",
    },
    {
      icon: <ZapIcon className="w-7 h-7 text-amber-500" />,
      count: 2,
      label: "workflows",
    },
    {
      icon: <Target02Icon className="w-7 h-7 text-indigo-500" />,
      count: 3,
      label: "goals",
    },
  ];

  const firstLine = sections.slice(0, 2);
  const secondLine = sections.slice(2);

  const cards = [
    { id: "emails", node: <DemoEmailsCard /> },
    { id: "events", node: <DemoEventsCard /> },
    { id: "todos", node: <DemoTodosCard /> },
    { id: "goals", node: <DemoGoalsCard /> },
    { id: "workflows", node: <DemoWorkflowsCard /> },
    { id: "conversations", node: <DemoConversationsCard /> },
  ];

  return (
    <div
      ref={ref}
      className="flex flex-col p-6 pt-0 min-h-full h-fit overflow-y-auto"
    >
      <m.div
        initial={{ opacity: 0, y: 16 }}
        animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 16 }}
        transition={{ duration: 0.5, ease: [0.32, 0.72, 0, 1] }}
        className="flex flex-col p-3 mb-10 space-y-1"
      >
        <div className="flex items-center gap-3 mb-5">
          <h2 className="text-4xl font-medium text-zinc-700">Good morning</h2>
          <h1 className="font-medium text-4xl text-zinc-700">
            Aryan
            <span className="ml-4">:)</span>
          </h1>
        </div>

        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-3xl text-zinc-500">
            <span>You have</span>
            {firstLine.map((section, index) => (
              <span key={section.label}>
                <span className="inline-flex items-center gap-1.5">
                  {section.icon}
                  <span className="font-medium text-white">
                    {section.count}
                  </span>
                  <span>{section.label}</span>
                </span>
                {index < firstLine.length - 1 && <span>,</span>}
                {index === firstLine.length - 1 && <span>,</span>}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-3xl text-zinc-500">
            {secondLine.map((section, index) => (
              <span key={section.label}>
                <span className="inline-flex items-center gap-1.5">
                  {section.icon}
                  <span className="font-medium text-white">
                    {section.count}
                  </span>
                  <span>{section.label}</span>
                </span>
                {index < secondLine.length - 1 && <span>,</span>}
                {index === secondLine.length - 2 && <span> and</span>}
                {index === secondLine.length - 1 && <span> today.</span>}
              </span>
            ))}
          </div>
        </div>
      </m.div>

      <div className="relative flex h-fit w-full snap-start flex-col items-center justify-center">
        <div className="mb-20 grid min-h-screen w-full grid-cols-1 sm:grid-cols-2 sm:space-y-0">
          {cards.map((card, i) => (
            <m.div
              key={card.id}
              initial={{ opacity: 0, y: 20 }}
              animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
              transition={{
                duration: 0.4,
                ease: [0.32, 0.72, 0, 1],
                delay: 0.3 + i * 0.1,
              }}
            >
              {card.node}
            </m.div>
          ))}
        </div>
      </div>
    </div>
  );
}
