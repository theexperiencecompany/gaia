import { Alert01Icon, ArrowRight02Icon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

export default function ProductBriefCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-2">
        {getToolCategoryIcon("linear", {
          width: 14,
          height: 14,
          showBackground: false,
        })}
        <span className="text-sm font-medium text-zinc-100">
          Product Brief — Thursday, March 6
        </span>
      </div>

      <div>
        {/* Sprint Status */}
        <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500 mb-1 mt-3">
          Sprint Status · Sprint 24, Day 6 of 10
        </p>
        <div className="mt-1 mb-2 rounded-full bg-zinc-700 h-1.5">
          <div
            className="h-1.5 rounded-full bg-primary"
            style={{ width: "64%" }}
          />
        </div>
        <p className="text-xs text-zinc-400">14 / 22 tickets done</p>
        <div className="mt-2 space-y-1">
          <p className="flex items-center gap-1 text-xs text-red-400">
            <Alert01Icon width={12} height={12} />3 tickets blocked (ENG-441,
            ENG-445, ENG-449)
          </p>
          <p className="flex items-center gap-1 text-xs text-emerald-400">
            <ArrowRight02Icon width={12} height={12} />
            Mobile checkout: on track
          </p>
          <p className="flex items-center gap-1 text-xs text-amber-400">
            <ArrowRight02Icon width={12} height={12} />
            Auth refactor: 2 days behind
          </p>
        </div>

        {/* Shipped Yesterday */}
        <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500 mb-1 mt-3">
          Shipped Yesterday
        </p>
        <div className="space-y-1">
          <p className="flex items-center gap-1 text-xs text-zinc-300">
            <ArrowRight02Icon
              width={12}
              height={12}
              className="text-zinc-500"
            />
            feat/dark-mode merged, deployed to prod (v2.4.1)
          </p>
          <p className="flex items-center gap-1 text-xs text-zinc-300">
            <ArrowRight02Icon
              width={12}
              height={12}
              className="text-zinc-500"
            />
            fix/search-timeout resolved (user-reported bug)
          </p>
        </div>

        {/* Today's Meetings */}
        <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500 mb-1 mt-3">
          Today&apos;s Meetings
        </p>
        <div className="space-y-1">
          <p className="text-xs text-zinc-400">
            10am — Sprint planning (45 min)
          </p>
          <p className="text-xs text-zinc-400">
            2pm — Stakeholder review with CEO
          </p>
          <p className="text-xs text-zinc-400">
            4pm — User interview (TechCorp)
          </p>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-zinc-800">
        <p className="flex items-center gap-1 text-[11px] text-red-400">
          <Alert01Icon width={12} height={12} />1 critical blocker needs your
          call before 10am
        </p>
      </div>
    </div>
  );
}
