import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const HANDLED_ITEMS = [
  {
    id: "pro-1",
    icon: "gmail",
    label: "Investor update drafted",
    detail: "2h saved",
  },
  {
    id: "pro-2",
    icon: "hubspot",
    label: "Acme follow-up queued — trial ends Friday",
    detail: "flagged",
  },
  {
    id: "pro-3",
    icon: "slack",
    label: "47 Slack threads summarized",
    detail: "30min saved",
  },
  {
    id: "pro-4",
    icon: "googlesheets",
    label: "Pipeline report built from latest metrics",
    detail: "1.5h saved",
  },
];

export default function ProactiveCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-medium text-zinc-400">
          Handled while you were focused
        </span>
        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
          ~4h saved today
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
            <span className="text-[11px] text-emerald-400">{item.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
