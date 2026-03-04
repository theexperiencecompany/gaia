import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const HANDLED_ITEMS = [
  {
    id: "sp-1",
    icon: "hubspot",
    label: "6 deal stages updated from email signals",
    detail: "25min saved",
    flagged: false,
  },
  {
    id: "sp-2",
    icon: "gmail",
    label: "Acme Corp follow-up drafted — trial ends Fri",
    detail: "flagged",
    flagged: true,
  },
  {
    id: "sp-3",
    icon: "linkedin",
    label: "TechFlow contact changed roles — flagged",
    detail: "flagged",
    flagged: true,
  },
  {
    id: "sp-4",
    icon: "hubspot",
    label: "Weekly pipeline report built automatically",
    detail: "1.5h saved",
    flagged: false,
  },
];

export default function SalesProactiveCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-medium text-zinc-400">
          Handled while you were in meetings
        </span>
        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
          ~3.5h saved today
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
              className={`text-[11px] ${item.flagged ? "text-red-400" : "text-emerald-400"}`}
            >
              {item.detail}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
