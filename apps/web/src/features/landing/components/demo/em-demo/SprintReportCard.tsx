import { ArrowRight02Icon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const METRICS = [
  {
    id: "sr-1",
    value: "Velocity: 87%",
    valueClass: "text-sm font-semibold text-emerald-400",
    label: "Sprint performance",
  },
  {
    id: "sr-2",
    value: "Tickets: 19/22 done",
    valueClass: "text-sm font-semibold text-white",
    label: "Completion",
  },
  {
    id: "sr-3",
    value: "Avg PR time: 18.4h",
    valueClass: "text-sm font-semibold text-amber-400",
    label: "Review cycle",
  },
  {
    id: "sr-4",
    value: "Deployments: 4",
    valueClass: "text-sm font-semibold text-white",
    label: "Shipped",
  },
];

const WENT_WELL = [
  "Dark mode shipped 3 weeks early",
  "Incident response time: 12 min avg (best ever)",
  "Zero rollbacks this sprint",
];

const TO_IMPROVE = [
  "PR review bottleneck (PR #214 stalled 4 days)",
  "Dev's OOO caused ENG-412 to slip",
];

export default function SprintReportCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="flex items-center gap-2">
        {getToolCategoryIcon("notion", {
          width: 14,
          height: 14,
          showBackground: false,
        })}
        <span className="flex-1 text-sm font-medium text-zinc-100">
          Sprint 24 Report
        </span>
        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
          Completed
        </span>
      </div>
      <p className="text-[11px] text-zinc-500 mt-0.5">
        Sprint 24 · Mar 3 – Mar 14 · 10 days
      </p>

      <div className="grid grid-cols-2 gap-2 my-3">
        {METRICS.map((metric) => (
          <div key={metric.id} className="rounded-lg bg-zinc-900 p-2">
            <p className={metric.valueClass}>{metric.value}</p>
            <p className="text-[10px] text-zinc-500">{metric.label}</p>
          </div>
        ))}
      </div>

      <div className="space-y-2.5">
        <div>
          <div className="flex items-center gap-1.5 mb-1">
            <div className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
              What went well
            </p>
          </div>
          <div className="rounded-xl bg-zinc-900 p-3 space-y-1">
            {WENT_WELL.map((item) => (
              <p
                key={item}
                className="flex items-start gap-1 text-xs text-zinc-300"
              >
                <ArrowRight02Icon
                  width={12}
                  height={12}
                  className="shrink-0 mt-0.5 text-emerald-400"
                />
                {item}
              </p>
            ))}
          </div>
        </div>

        <div>
          <div className="flex items-center gap-1.5 mb-1">
            <div className="h-1.5 w-1.5 rounded-full bg-amber-400" />
            <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
              What to improve
            </p>
          </div>
          <div className="rounded-xl bg-zinc-900 p-3 space-y-1">
            {TO_IMPROVE.map((item) => (
              <p
                key={item}
                className="flex items-start gap-1 text-xs text-zinc-400"
              >
                <ArrowRight02Icon
                  width={12}
                  height={12}
                  className="shrink-0 mt-0.5 text-amber-400"
                />
                {item}
              </p>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-2 pt-2 border-t border-zinc-800">
        <p className="text-[11px] text-zinc-500">
          Posted to #engineering + Notion Sprint Archive
        </p>
      </div>
    </div>
  );
}
