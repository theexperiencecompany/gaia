import { Alert01Icon, ArrowRight02Icon, CheckmarkCircle02Icon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

export default function OneOnOnePrepCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-0.5 flex items-center gap-2">
        {getToolCategoryIcon("googlecalendar", {
          width: 14,
          height: 14,
          showBackground: false,
        })}
        <span className="text-sm font-medium text-zinc-100">
          1:1 Prep — Alex M.
        </span>
      </div>
      <p className="mb-1 text-[11px] text-zinc-500">Today, 2:00 PM</p>

      <div>
        <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500 mb-1 mt-3">
          This Sprint
        </p>
        <div className="rounded-lg bg-zinc-900 p-2.5 space-y-1">
          <p className="flex items-start gap-1 text-xs text-emerald-400">
            <CheckmarkCircle02Icon
              width={12}
              height={12}
              className="shrink-0 mt-0.5"
            />
            Merged 4 PRs (avg +347 lines, solid output)
          </p>
          <p className="flex items-start gap-1 text-xs text-emerald-400">
            <CheckmarkCircle02Icon
              width={12}
              height={12}
              className="shrink-0 mt-0.5"
            />
            Closed 6 Linear tickets (ENG-398, ENG-399, ENG-401, ENG-403,
            ENG-408, ENG-411)
          </p>
          <p className="flex items-start gap-1 text-xs text-amber-400">
            <Alert01Icon width={12} height={12} className="shrink-0 mt-0.5" />
            PR #214 (feat/auth-refactor) waiting 4 days for review — blocker
          </p>
        </div>

        <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500 mb-1 mt-3">
          Potential topics
        </p>
        <div className="rounded-lg bg-zinc-900 p-2.5 space-y-1">
          <p className="flex items-start gap-1 text-xs text-zinc-300">
            <ArrowRight02Icon
              width={12}
              height={12}
              className="shrink-0 mt-0.5 text-zinc-500"
            />
            Career: Expressed interest in staff eng path (March 1 Slack DM)
          </p>
          <p className="flex items-start gap-1 text-xs text-zinc-300">
            <ArrowRight02Icon
              width={12}
              height={12}
              className="shrink-0 mt-0.5 text-zinc-500"
            />
            Blocker: API schema decision (ENG-407) stalling her work
          </p>
          <p className="flex items-start gap-1 text-xs text-zinc-300">
            <ArrowRight02Icon
              width={12}
              height={12}
              className="shrink-0 mt-0.5 text-zinc-500"
            />
            Recognition: Led incident response cleanly last Tuesday
          </p>
        </div>

        <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500 mb-1 mt-3">
          From last 1:1 (Feb 20)
        </p>
        <div className="rounded-lg bg-zinc-900 p-2.5 space-y-1">
          <p className="text-xs text-zinc-400">
            • Action: you&apos;d get clarity on Q2 roadmap — not yet shared
          </p>
          <p className="flex items-center gap-1 text-xs text-zinc-400">
            • Action: she&apos;d ramp on Rust — 2 merged PRs using it{" "}
            <CheckmarkCircle02Icon
              width={12}
              height={12}
              className="text-emerald-400"
            />
          </p>
        </div>
      </div>

      <div className="mt-2 pt-2 border-t border-zinc-800">
        <p className="text-[11px] text-amber-400">
          Open questions: 1 (ENG-407 API schema — needs your decision)
        </p>
      </div>
    </div>
  );
}
