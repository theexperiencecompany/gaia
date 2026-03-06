import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const HANDLED_ITEMS = [
  {
    id: "em-1",
    icon: "github",
    label: "2 PRs flagged — PR #214 stale for 4 days",
    detail: "flagged",
    detailClass: "text-red-400",
  },
  {
    id: "em-2",
    icon: "linear",
    label: "Sprint velocity report compiled for retro",
    detail: "1.5h saved",
    detailClass: "text-emerald-400",
  },
  {
    id: "em-3",
    icon: "slack",
    label: "Cross-team dependency escalated to #platform",
    detail: "done",
    detailClass: "text-zinc-500",
  },
  {
    id: "em-4",
    icon: "sentry",
    label: "P2 error grouped with past incidents — triaged",
    detail: "done",
    detailClass: "text-zinc-500",
  },
];

export default function EMProactiveCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-medium text-zinc-400">
          Handled while you were in 1:1s
        </span>
        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
          ~4h saved today
        </span>
      </div>
      <div className="space-y-2.5">
        {HANDLED_ITEMS.map((item) => {
          const iconElement = getToolCategoryIcon(item.icon, {
            width: 14,
            height: 14,
            showBackground: false,
          });
          return (
            <div key={item.id} className="flex items-center gap-2.5 text-sm">
              <div className="flex h-4 w-4 shrink-0 items-center justify-center">
                {iconElement ?? (
                  <div className="h-3 w-3 rounded-full bg-red-500/70" />
                )}
              </div>
              <span className="flex-1 text-zinc-300">{item.label}</span>
              <span className={`text-[11px] ${item.detailClass}`}>
                {item.detail}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
