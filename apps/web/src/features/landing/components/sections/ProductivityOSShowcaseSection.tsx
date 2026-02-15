"use client";

import {
  Calendar01Icon,
  CheckListIcon,
  DashboardSquare02Icon,
  ZapIcon,
} from "@icons";
import { AnimatePresence, m, useInView } from "motion/react";
import type React from "react";
import { useEffect, useRef, useState } from "react";
import DemoCalendarView from "../demo/calendar-demo/DemoCalendarView";
import DemoChatHeader from "../demo/DemoChatHeader";
import DemoSidebar from "../demo/DemoSidebar";
import DemoDashboardView from "../demo/dashboard-demo/DemoDashboardView";
import DemoTodosView from "../demo/todos-demo/DemoTodosView";
import type { DemoPage } from "../demo/types";
import DemoWorkflowsView from "../demo/workflows-demo/DemoWorkflowsView";
import ShowcaseSectionLayout from "./ShowcaseSectionLayout";

// ─── Config ───────────────────────────────────────────────────────────────────

const DURATION = 5000; // ms per feature
const TICK = 50; // interval tick in ms

// ─── Features ─────────────────────────────────────────────────────────────────

const FEATURES: Array<{
  id: DemoPage;
  Icon: React.ComponentType<{
    width?: number;
    height?: number;
    className?: string;
  }>;
  title: string;
  description: string;
}> = [
  {
    id: "dashboard",
    Icon: DashboardSquare02Icon,
    title: "Dashboard",
    description:
      "Your tasks, calendar, conversations, and workflows pulled into a single live view. See exactly what needs attention today — without opening five different apps.",
  },
  {
    id: "calendar",
    Icon: Calendar01Icon,
    title: "Calendar",
    description:
      "GAIA understands your schedule, not just displays it. Back-to-back meetings, deep work blocks, upcoming deadlines — it sees it all and can act on it from a single message.",
  },
  {
    id: "todos",
    Icon: CheckListIcon,
    title: "Todos",
    description:
      "Write a task in plain English. GAIA sets the priority, builds the workflow, and executes it. When it's done, the task closes itself. Zero follow-up.",
  },
  {
    id: "workflows",
    Icon: ZapIcon,
    title: "Workflows",
    description:
      "Describe the automation once. GAIA wires the triggers, connects your tools, and runs it on repeat — morning digests, meeting notes, PR alerts. All handled.",
  },
];

// ─── Demo Window ──────────────────────────────────────────────────────────────

function ProductivityOSDemo({
  activePage,
  onPageChange,
}: {
  activePage: DemoPage;
  onPageChange: (page: DemoPage) => void;
}) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="overflow-hidden rounded-2xl" style={{ height: "600px" }}>
      {/* App shell */}
      <div className="flex h-full" style={{ backgroundColor: "#111111" }}>
        <DemoSidebar
          open={sidebarOpen}
          activePage={activePage}
          onPageChange={onPageChange}
        />

        <div className="relative flex min-w-0 flex-1 flex-col">
          <DemoChatHeader
            sidebarOpen={sidebarOpen}
            activePage={activePage}
            onToggleSidebar={() => setSidebarOpen((o) => !o)}
            onNotificationsClick={() => {}}
          />

          <div className="flex flex-1 overflow-hidden">
            {activePage === "dashboard" && (
              <div className="flex-1 overflow-y-auto">
                <DemoDashboardView />
              </div>
            )}
            {activePage === "calendar" && (
              <div className="flex flex-1 overflow-hidden">
                <DemoCalendarView />
              </div>
            )}
            {activePage === "todos" && (
              <div className="flex flex-1 overflow-hidden">
                <DemoTodosView />
              </div>
            )}
            {activePage === "workflows" && (
              <div className="flex-1 overflow-y-auto">
                <DemoWorkflowsView />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Right Sidebar ────────────────────────────────────────────────────────────

function ProductivityOSSidebar({
  activePage,
  progress,
  onPageChange,
}: {
  activePage: DemoPage;
  progress: number;
  onPageChange: (page: DemoPage) => void;
}) {
  return (
    <div className="flex flex-col">
      <div className="mb-2 font-serif text-3xl text-primary">
        Productivity OS
      </div>
      <p className="mb-8 text-sm font-light leading-relaxed text-zinc-500">
        Every tool your work runs on — tasks, time, and automation — built into
        one connected system.
      </p>

      {FEATURES.map((feature) => {
        const isActive = activePage === feature.id;
        const { Icon } = feature;

        return (
          <button
            key={feature.id}
            type="button"
            onClick={() => onPageChange(feature.id)}
            className="group w-full cursor-pointer border-t border-white/6 pt-4 pb-2 text-left last:border-b"
          >
            {/* Title row */}
            <div className="flex items-center gap-2">
              <Icon
                width={22}
                height={22}
                className={
                  isActive
                    ? "text-primary"
                    : "text-zinc-600 group-hover:text-zinc-400"
                }
              />
              <span
                className={`text-xl font-medium tracking-tight transition-colors ${
                  isActive
                    ? "text-white"
                    : "text-zinc-500 group-hover:text-zinc-300"
                }`}
              >
                {feature.title}
              </span>
            </div>

            {/* Progress bar — only visible when active */}
            {isActive && (
              <div className="mt-3 h-[2px] w-full overflow-hidden rounded-full bg-white/6">
                <div
                  className="h-full rounded-full bg-primary transition-none"
                  style={{ width: `${progress}%` }}
                />
              </div>
            )}

            {/* Expandable description */}
            <AnimatePresence initial={false}>
              {isActive && (
                <m.div
                  key="desc"
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
                  className="overflow-hidden"
                >
                  <p className="mt-3 text-sm font-light leading-relaxed text-zinc-500">
                    {feature.description}
                  </p>
                </m.div>
              )}
            </AnimatePresence>
          </button>
        );
      })}
    </div>
  );
}

// ─── Section ──────────────────────────────────────────────────────────────────

export default function ProductivityOSShowcaseSection() {
  const [activePage, setActivePage] = useState<DemoPage>("dashboard");
  const [progress, setProgress] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const isInView = useInView(containerRef, { once: true, amount: 0.2 });

  // Refs for mutable state — avoids stale closures in the interval
  const stateRef = useRef({ activePage: "dashboard" as DemoPage, elapsed: 0 });

  const handlePageChange = (page: DemoPage) => {
    stateRef.current.activePage = page;
    stateRef.current.elapsed = 0;
    setActivePage(page);
    setProgress(0);
  };

  useEffect(() => {
    // Only start the interval when the section is in view
    if (!isInView) return;

    const interval = setInterval(() => {
      stateRef.current.elapsed += TICK;
      const p = Math.min((stateRef.current.elapsed / DURATION) * 100, 100);
      setProgress(p);

      if (stateRef.current.elapsed >= DURATION) {
        stateRef.current.elapsed = 0;
        const currentIdx = FEATURES.findIndex(
          (f) => f.id === stateRef.current.activePage,
        );
        const nextPage = FEATURES[(currentIdx + 1) % FEATURES.length].id;
        stateRef.current.activePage = nextPage;
        setActivePage(nextPage);
        setProgress(0);
      }
    }, TICK);

    return () => clearInterval(interval);
  }, [isInView]);

  return (
    <div ref={containerRef}>
      <ShowcaseSectionLayout
        DemoComponent={
          <ProductivityOSDemo
            activePage={activePage}
            onPageChange={handlePageChange}
          />
        }
        SidebarContent={
          <ProductivityOSSidebar
            activePage={activePage}
            progress={progress}
            onPageChange={handlePageChange}
          />
        }
        containerClassName="relative mx-auto mb-8 sm:mb-16 lg:mb-20 flex w-full flex-col justify-center px-6 sm:px-4"
        sidebarClassName="flex w-full flex-col justify-center lg:w-[28%]"
      />
    </div>
  );
}
