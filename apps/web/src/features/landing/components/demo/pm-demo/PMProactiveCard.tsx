import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const HANDLED_ITEMS = [
  {
    id: "pm-pro-1",
    icon: "linear",
    label: "Sprint progress report drafted for Monday",
    detail: "45min saved",
    detailVariant: "saved",
  },
  {
    id: "pm-pro-2",
    icon: "slack",
    label: "4 feature requests captured and triaged",
    detail: "done",
    detailVariant: "done",
  },
  {
    id: "pm-pro-3",
    icon: "github",
    label: "2 deployments tracked + release notes drafted",
    detail: "done",
    detailVariant: "done",
  },
  {
    id: "pm-pro-4",
    icon: "notion",
    label: "Roadmap doc synced with latest Linear milestones",
    detail: "20min saved",
    detailVariant: "saved",
  },
];

export default function PMProactiveCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-medium text-zinc-400">
          Handled while you were in product reviews
        </span>
        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
          ~3h saved today
        </span>
      </div>
      <div className="space-y-2.5">
        {HANDLED_ITEMS.map((item) => (
          <div key={item.id} className="flex items-center gap-2.5 text-sm">
            <div className="flex h-4 w-4 shrink-0 items-center justify-center">
              {getToolCategoryIcon(item.icon, {
                width: 14,
                height: 14,
                showBackground: false,
              })}
            </div>
            <span className="flex-1 text-zinc-300">{item.label}</span>
            <span
              className={`text-[11px] ${item.detailVariant === "saved" ? "text-emerald-400" : "text-zinc-500"}`}
            >
              {item.detail}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
