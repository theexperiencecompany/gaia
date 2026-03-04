import { Alert01Icon, ArrowRight02Icon, CheckmarkCircle02Icon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const YESTERDAY_ITEMS = [
  {
    id: "y-1",
    text: "Merged feat/auth-refactor",
    meta: "PR #214, +847 -312",
  },
  {
    id: "y-2",
    text: "Resolved 3 Linear tickets:",
    meta: "ENG-401, ENG-398, ENG-392",
  },
];

const TODAY_ITEMS = [
  {
    id: "t-1",
    text: "Finish API rate limiting",
    meta: "ENG-405",
  },
  {
    id: "t-2",
    text: "Review Maya's PR on /api/users endpoint",
    meta: null,
  },
];

const BLOCKER_ITEMS = [
  {
    id: "b-1",
    text: "Waiting on design spec for settings modal",
    meta: "ENG-407",
  },
];

export default function StandupCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-2">
        {getToolCategoryIcon("github", {
          width: 14,
          height: 14,
          showBackground: false,
        })}
        <span className="text-[11px] font-medium text-zinc-300">
          Daily Standup — Thursday, March 6
        </span>
      </div>

      <div className="space-y-3">
        <div>
          <span className="text-[11px] font-medium uppercase tracking-wide text-emerald-400">
            Yesterday
          </span>
          <div className="mt-1.5 space-y-1.5">
            {YESTERDAY_ITEMS.map((item) => (
              <div key={item.id} className="flex items-baseline gap-1.5">
                <CheckmarkCircle02Icon
                  className="shrink-0 text-emerald-400"
                  width={12}
                  height={12}
                />
                <span className="text-xs text-zinc-300">{item.text}</span>
                {item.meta && (
                  <span className="font-mono text-xs text-zinc-500">
                    {item.meta}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>

        <div>
          <span className="text-[11px] font-medium uppercase tracking-wide text-primary">
            Today
          </span>
          <div className="mt-1.5 space-y-1.5">
            {TODAY_ITEMS.map((item) => (
              <div key={item.id} className="flex items-baseline gap-1.5">
                <ArrowRight02Icon
                  className="shrink-0 text-primary"
                  width={12}
                  height={12}
                />
                <span className="text-xs text-zinc-300">{item.text}</span>
                {item.meta && (
                  <span className="font-mono text-xs text-zinc-500">
                    {item.meta}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>

        <div>
          <span className="text-[11px] font-medium uppercase tracking-wide text-amber-400">
            Blockers
          </span>
          <div className="mt-1.5 space-y-1.5">
            {BLOCKER_ITEMS.map((item) => (
              <div key={item.id} className="flex items-baseline gap-1.5">
                <Alert01Icon
                  className="shrink-0 text-amber-400"
                  width={12}
                  height={12}
                />
                <span className="text-xs text-zinc-300">{item.text}</span>
                {item.meta && (
                  <span className="font-mono text-xs text-zinc-500">
                    {item.meta}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
