import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const HANDLED_ITEMS = [
  {
    id: "dev-1",
    icon: "github",
    label: "3 PRs merged — standup draft ready",
    detail: "45min saved",
    urgent: false,
  },
  {
    id: "dev-2",
    icon: "linear",
    label: "2 tickets moved to Done automatically",
    detail: "done",
    urgent: false,
  },
  {
    id: "dev-3",
    icon: "slack",
    label: "31 Slack threads summarized",
    detail: "25min saved",
    urgent: false,
  },
  {
    id: "dev-4",
    icon: "sentry",
    label: "1 production error flagged — P1 triage",
    detail: "flagged",
    urgent: true,
  },
];

export default function DevProactiveCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-medium text-zinc-400">
          Handled while you were in deep work
        </span>
        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
          ~2h saved today
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
                  <div className="h-3 w-3 rounded-full bg-red-500" />
                )}
              </div>
              <span className="flex-1 text-zinc-300">{item.label}</span>
              <span
                className={`text-[11px] ${item.urgent ? "text-red-400" : "text-emerald-400"}`}
              >
                {item.detail}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
