"use client";

import { Tabs } from "@heroui/react";
import { Comment01Icon } from "@icons";
import { type ReactNode, useState } from "react";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { tabsVariants } from "@/components/shared/tabsVariants";
import { cn } from "@/lib/utils";
import { appName } from "../marketplace/appModel";
import { AppIcon } from "./AppIcon";
import { isRepeating, type Task, type TaskRun } from "./taskModel";
import { WEBHOOK_TRIGGER } from "./whenModel";

const RUN_OUTCOME: Record<TaskRun["outcome"], { label: string; tone: string }> =
  {
    success: { label: "Done", tone: "bg-emerald-400/10 text-emerald-400" },
    failed: { label: "Failed", tone: "bg-red-400/10 text-red-400" },
    skipped: { label: "Skipped", tone: "bg-zinc-800 text-zinc-400" },
  };

/** The filled tabs the workflow window's side panel uses, on a sunken full-width track. */
const tabs = tabsVariants({ variant: "sunken", size: "sm", color: "accent" });

const Empty = ({ children }: { children: string }) => (
  <p className="text-sm text-zinc-500">{children}</p>
);

function Notes({ task }: { task: Task }) {
  if (!task.canvas?.length) {
    return <Empty>GAIA keeps its notes here once it starts.</Empty>;
  }
  return (
    <div className="space-y-4">
      {task.canvas.map((section) => (
        <section key={section.heading}>
          <h4 className="text-xs font-medium text-zinc-500">
            {section.heading}
          </h4>
          <p className="mt-1 text-sm leading-6 text-zinc-200">{section.body}</p>
        </section>
      ))}
    </div>
  );
}

/** What started a run (trigger_type), as it reads after the time. */
function startedBy(trigger: TaskRun["trigger"]): string {
  if (trigger === "manual") return "Started by you";
  if (trigger === "schedule") return "On schedule";
  if (trigger === "watch") return "When it saw the change";
  if (trigger === WEBHOOK_TRIGGER) return "From the webhook";
  return `From ${appName(trigger)}`;
}

/** One run: its summary and time; open, what GAIA did in it and its chat. */
function RunLine({
  run,
  isOpen,
  onToggle,
}: {
  run: TaskRun;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <li>
      <div className="relative -mx-2">
        <GaiaButton
          aria-label={`${run.summary}, ${run.at}`}
          aria-expanded={isOpen}
          variant="row"
          shape="sm"
          inset="none"
          onPress={onToggle}
          className="absolute inset-0 h-full w-full min-w-0"
        />
        <div className="pointer-events-none relative flex items-start justify-between gap-3 px-2 py-1.5">
          <div className="min-w-0">
            <p className="text-sm leading-5 text-zinc-200">{run.summary}</p>
            <p className="mt-0.5 text-xs tabular-nums text-zinc-500">
              {run.at}
            </p>
          </div>
          <span
            className={cn(
              "shrink-0 rounded-full px-2 py-0.5 text-xs",
              RUN_OUTCOME[run.outcome].tone,
            )}
          >
            {RUN_OUTCOME[run.outcome].label}
          </span>
        </div>
      </div>
      {isOpen && (
        <div className="space-y-2 pt-1.5 pb-1">
          {run.error && (
            <p className="text-sm leading-5 text-red-400">{run.error}</p>
          )}
          {run.trace.length > 0 && (
            <ol className="space-y-1.5">
              {run.trace.map((call) => (
                <li
                  key={`${call.app}-${call.text}`}
                  className="flex items-start gap-2 text-sm leading-5 text-zinc-300"
                >
                  <span className="flex h-5 shrink-0 items-center">
                    <AppIcon id={call.app} size={14} />
                  </span>
                  {call.text}
                </li>
              ))}
            </ol>
          )}
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs tabular-nums text-zinc-500">
              {startedBy(run.trigger)}, took {run.duration}
            </p>
            <GaiaButton
              size="sm"
              variant="text"
              inset="snug"
              tone="faint"
              hoverTone="bright"
              className="h-6 min-w-0 gap-1 text-xs"
            >
              <Comment01Icon className="size-3.5" />
              Open chat
            </GaiaButton>
          </div>
        </div>
      )}
    </li>
  );
}

function Runs({ runs }: { runs: TaskRun[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  if (runs.length === 0) return <Empty>It hasn't run yet.</Empty>;
  return (
    <ul className="space-y-1.5">
      {runs.map((run) => (
        <RunLine
          key={run.id}
          run={run}
          isOpen={openId === run.id}
          onToggle={() => setOpenId(openId === run.id ? null : run.id)}
        />
      ))}
    </ul>
  );
}

/**
 * GAIA's side of a task, on its own surface: its runs (task_runs) and its notes
 * (canvas). A repeating task leads with its runs, a one-off task with its notes.
 */
export default function TaskRecord({ task }: { task: Task }) {
  const runs = {
    key: "runs",
    title: "Runs",
    body: <Runs runs={task.runs} />,
  };
  const notes = { key: "notes", title: "Notes", body: <Notes task={task} /> };
  const sections: { key: string; title: string; body: ReactNode }[] =
    // Each time a watch tells you is a run, so a watch leads with them as a repeat does.
    isRepeating(task.when) || task.when.watch ? [runs, notes] : [notes, runs];
  return (
    <div className="rounded-2xl bg-zinc-800/50 p-3">
      <Tabs aria-label="GAIA's record" className={tabs.base()}>
        <Tabs.List className={tabs.tabList()}>
          {sections.map((section) => (
            <Tabs.Tab
              key={section.key}
              id={section.key}
              className={tabs.tab({ className: "text-[13px] font-medium" })}
            >
              {section.title}
              <Tabs.Indicator className={tabs.tabIndicator()} />
            </Tabs.Tab>
          ))}
        </Tabs.List>
        {sections.map((section) => (
          <Tabs.Panel
            key={section.key}
            id={section.key}
            className={tabs.tabPanel()}
          >
            {section.body}
          </Tabs.Panel>
        ))}
      </Tabs>
    </div>
  );
}
