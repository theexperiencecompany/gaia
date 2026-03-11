import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const HANDLED_ITEMS = [
  {
    id: "ap-1",
    icon: "clickup",
    label: "TechCorp weekly report drafted and ready to send",
    detail: "1.5h saved",
    detailColor: "text-emerald-400",
  },
  {
    id: "ap-2",
    icon: "gmail",
    label: "2 inbound leads triaged — 1 hot, 1 qualified",
    detail: "done",
    detailColor: "text-zinc-500",
  },
  {
    id: "ap-3",
    icon: "slack",
    label: "At-risk project flagged — ByteScale 3 days behind",
    detail: "flagged",
    detailColor: "text-red-400",
  },
  {
    id: "ap-4",
    icon: "asana",
    label: "4 overdue tasks reassigned across 2 projects",
    detail: "30min saved",
    detailColor: "text-emerald-400",
  },
];

const FALLBACK_ICONS: Record<string, React.ReactNode> = {
  clickup: <div className="h-3 w-3 rounded-full bg-purple-400" />,
  asana: <div className="h-3 w-3 rounded-full bg-red-400/70" />,
};

export default function AgencyProactiveCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-medium text-zinc-400">
          Handled while you were in client calls
        </span>
        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
          ~5h saved today
        </span>
      </div>
      <div className="space-y-2.5">
        {HANDLED_ITEMS.map((item) => {
          const icon =
            getToolCategoryIcon(item.icon, {
              width: 14,
              height: 14,
              showBackground: false,
            }) ?? FALLBACK_ICONS[item.icon];

          return (
            <div key={item.id} className="flex items-center gap-2.5 text-sm">
              <div className="flex h-4 w-4 shrink-0 items-center justify-center">
                {icon}
              </div>
              <span className="flex-1 text-zinc-300">{item.label}</span>
              <span className={`text-[11px] ${item.detailColor}`}>
                {item.detail}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
