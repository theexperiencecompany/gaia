import { Alert01Icon, ArrowUp02Icon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const METRICS = [
  {
    id: "m-1",
    label: "Sprint velocity",
    value: "87%",
    valueClass: "text-xl font-semibold text-white",
    trendUp: true,
    trend: "from 79%",
    trendClass: "text-[10px] text-emerald-400",
  },
  {
    id: "m-2",
    label: "PR cycle time",
    value: "18.4h",
    valueClass: "text-xl font-semibold text-white",
    trendUp: true,
    trend: "from 12h",
    trendClass: "text-[10px] text-red-400",
  },
  {
    id: "m-3",
    label: "Completion rate",
    value: "64%",
    valueClass: "text-xl font-semibold text-white",
    trendUp: false,
    trend: "on track",
    trendClass: "text-[10px] text-emerald-400",
  },
];

const TEAM_MEMBERS = [
  {
    id: "t-1",
    name: "Alex M.",
    dotClass: "bg-emerald-400",
    status: "4 tickets done · 1 PR in review · no blockers",
  },
  {
    id: "t-2",
    name: "Sarah K.",
    dotClass: "bg-amber-400",
    status: "2 tickets done · PR #214 awaiting review (4d)",
  },
  {
    id: "t-3",
    name: "Maya R.",
    dotClass: "bg-amber-400",
    status: "Blocked on API schema decision (ENG-407)",
  },
  {
    id: "t-4",
    name: "James T.",
    dotClass: "bg-emerald-400",
    status: "3 tickets done · led incident response",
  },
  {
    id: "t-5",
    name: "Dev K.",
    dotClass: "bg-red-400",
    status: "OOO until Thursday · ENG-412 unassigned",
  },
];

export default function TeamHealthCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-2">
        {getToolCategoryIcon("linear", {
          width: 14,
          height: 14,
          showBackground: false,
        })}
        <span className="text-sm font-medium text-zinc-100">
          Team Health — Sprint 24, Day 6
        </span>
      </div>

      <div className="flex gap-2">
        {METRICS.map((metric) => (
          <div
            key={metric.id}
            className="flex flex-1 flex-col items-center rounded-lg bg-zinc-900 p-2 text-center"
          >
            <p className="text-[10px] text-zinc-500 mb-0.5">{metric.label}</p>
            <p className={metric.valueClass}>{metric.value}</p>
            <p
              className={`${metric.trendClass} flex items-center justify-center gap-0.5`}
            >
              {metric.trendUp && <ArrowUp02Icon width={10} height={10} />}
              {metric.trend}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-3">
        <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-zinc-500">
          Team status
        </p>
        <div className="rounded-xl bg-zinc-900 p-3">
          {TEAM_MEMBERS.map((member) => (
            <div
              key={member.id}
              className="flex items-center gap-2.5 py-1.5 border-b border-zinc-700/50 last:border-0"
            >
              <div
                className={`h-2 w-2 rounded-full shrink-0 ${member.dotClass}`}
              />
              <span className="text-xs font-medium text-zinc-200 w-16 shrink-0">
                {member.name}
              </span>
              <span className="text-xs text-zinc-400 flex-1">
                {member.status}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-2 pt-2 border-t border-zinc-800">
        <p className="flex items-center gap-1 text-[11px] text-amber-400">
          <Alert01Icon width={12} height={12} />
          PR cycle time up 53% — likely PR #214 bottleneck
        </p>
      </div>
    </div>
  );
}
