"use client";

import { Tabs } from "@heroui/react";
import type { ReactNode } from "react";

import { tabsVariants } from "@/components/shared/tabsVariants";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import WorkflowSteps from "@/features/workflows/components/shared/WorkflowSteps";
import { cn } from "@/lib/utils";
import { isRepeating, type Task, type TaskRun } from "./taskModel";

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

function Activity({ task }: { task: Task }) {
  if (task.activity.length === 0) return <Empty>Nothing yet.</Empty>;
  return (
    <ol className="space-y-3">
      {[...task.activity].reverse().map((event) => (
        <li key={`${event.at}-${event.text}`}>
          <p className="text-sm leading-5 text-zinc-200">{event.text}</p>
          <p className="mt-0.5 text-xs tabular-nums text-zinc-500">
            {event.at}
          </p>
        </li>
      ))}
    </ol>
  );
}

function Runs({ runs }: { runs: TaskRun[] }) {
  if (runs.length === 0) return <Empty>It hasn't run yet.</Empty>;
  return (
    <ul className="space-y-3">
      {runs.map((run) => (
        <li key={run.id} className="flex items-start justify-between gap-3">
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
        </li>
      ))}
    </ul>
  );
}

/**
 * GAIA's side of a task, on its own surface: a repeating workflow shows its runs
 * and steps, a one-off task its notes and activity.
 */
export default function TaskRecord({
  task,
  steps = [],
}: {
  task: Task;
  /** workflow.steps: what GAIA worked out it does on each run. */
  steps?: Workflow["steps"];
}) {
  const runsAgain = isRepeating(task.when) || task.runs.length > 0;
  const sections: { key: string; title: string; body: ReactNode }[] = runsAgain
    ? [
        { key: "runs", title: "Runs", body: <Runs runs={task.runs} /> },
        {
          key: "steps",
          title: "Steps",
          body:
            steps.length > 0 ? (
              <WorkflowSteps steps={steps} />
            ) : (
              <Empty>GAIA works out the steps on the first run.</Empty>
            ),
        },
      ]
    : [
        { key: "notes", title: "Notes", body: <Notes task={task} /> },
        { key: "activity", title: "Activity", body: <Activity task={task} /> },
      ];
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
