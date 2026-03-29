"use client";

import { m, useInView } from "motion/react";
import { useRef } from "react";
import { cn } from "@/lib/utils";

// ─── Widget: Emails ──────────────────────────────────────────────────────────

function EmailsWidget() {
  return (
    <div className="h-full rounded-2xl bg-zinc-800 p-4">
      <p className="text-xs text-zinc-500">Unread Emails</p>
      <p className="mt-1 text-3xl font-semibold text-zinc-200">12</p>
      <p className="mt-1 text-xs text-zinc-500">3 flagged</p>
    </div>
  );
}

// ─── Widget: Calendar ────────────────────────────────────────────────────────

function CalendarWidget() {
  return (
    <div className="h-full rounded-2xl bg-zinc-800 p-4">
      <p className="text-xs text-zinc-500">Today's Events</p>
      <div className="mt-2 space-y-2">
        <div className="rounded-2xl bg-zinc-900 p-3">
          <p className="text-sm text-zinc-200">10:00 Standup · 30m</p>
        </div>
        <div className="rounded-2xl bg-zinc-900 p-3">
          <p className="text-sm text-zinc-200">3:00 PM Demo · 45m</p>
        </div>
      </div>
    </div>
  );
}

// ─── Widget: Todos ───────────────────────────────────────────────────────────

const TODO_ITEMS = ["Review PR #47", "Send Q1 report", "Update roadmap"];

function TodosWidget() {
  return (
    <div className="h-full rounded-2xl bg-zinc-800 p-4">
      <p className="text-xs text-zinc-500">Tasks Due Today</p>
      <div className="mt-2 space-y-2">
        {TODO_ITEMS.map((item) => (
          <div key={item} className="flex items-center gap-2">
            <div className="h-4 w-4 shrink-0 rounded border border-zinc-600" />
            <p className="text-sm text-zinc-200">{item}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Widget: Workflows ───────────────────────────────────────────────────────

function WorkflowsWidget() {
  return (
    <div className="h-full rounded-2xl bg-zinc-800 p-4">
      <p className="text-xs text-zinc-500">Active Workflows</p>
      <div className="mt-2 flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
        </span>
        <p className="text-sm text-zinc-200">3 running</p>
      </div>
    </div>
  );
}

// ─── Widget: Recent Chats ────────────────────────────────────────────────────

function RecentChatsWidget() {
  return (
    <div className="h-full rounded-2xl bg-zinc-800 p-4">
      <p className="text-xs text-zinc-500">Recent Conversations</p>
      <div className="mt-2 space-y-2">
        <div className="rounded-2xl bg-zinc-900 p-3">
          <p className="text-sm text-zinc-200">GitHub PR summary</p>
          <p className="mt-0.5 text-xs text-zinc-500">2h ago</p>
        </div>
        <div className="rounded-2xl bg-zinc-900 p-3">
          <p className="text-sm text-zinc-200">Q1 budget analysis</p>
          <p className="mt-0.5 text-xs text-zinc-500">5h ago</p>
        </div>
      </div>
    </div>
  );
}

// ─── Widget wrapper with stagger animation ───────────────────────────────────

interface AnimatedWidgetProps {
  children: React.ReactNode;
  index: number;
  inView: boolean;
  className?: string;
}

function AnimatedWidget({
  children,
  index,
  inView,
  className,
}: AnimatedWidgetProps) {
  return (
    <m.div
      className={cn("h-full", className)}
      initial={{ opacity: 0, scale: 0.97 }}
      animate={inView ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.3, delay: index * 0.1 }}
    >
      {children}
    </m.div>
  );
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function DashboardDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true });

  return (
    <div ref={ref} className="grid grid-cols-2 gap-3">
      {/* Row 1: Stats row */}
      <AnimatedWidget index={0} inView={inView}>
        <EmailsWidget />
      </AnimatedWidget>
      <AnimatedWidget index={1} inView={inView}>
        <WorkflowsWidget />
      </AnimatedWidget>

      {/* Row 2: Calendar spans full width */}
      <AnimatedWidget index={2} inView={inView} className="col-span-2">
        <CalendarWidget />
      </AnimatedWidget>

      {/* Row 3: Todos + Recent chats */}
      <AnimatedWidget index={3} inView={inView}>
        <TodosWidget />
      </AnimatedWidget>
      <AnimatedWidget index={4} inView={inView}>
        <RecentChatsWidget />
      </AnimatedWidget>
    </div>
  );
}
