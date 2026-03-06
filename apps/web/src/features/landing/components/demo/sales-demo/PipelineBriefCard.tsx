import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const DEAL_ITEMS = [
  {
    id: "pb-1",
    company: "Acme Corp",
    value: "$48,000",
    sub: "Trial ends Friday · No onboarding booked",
    info: "Last contact: 6 days ago",
    infoColor: "text-zinc-500",
    urgent: true,
  },
  {
    id: "pb-2",
    company: "ByteScale",
    value: "$22,000",
    sub: "Went silent after demo · 9 days no reply",
    info: "Champion is still engaged on LinkedIn",
    infoColor: "text-zinc-500",
    urgent: false,
  },
  {
    id: "pb-3",
    company: "DataFlow",
    value: "$91,000",
    sub: "New champion introduced last week",
    info: "Action: re-engage with new contact",
    infoColor: "text-primary",
    urgent: false,
  },
];

export default function PipelineBriefCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-1 flex items-center gap-2">
        {getToolCategoryIcon("hubspot", {
          width: 16,
          height: 16,
          showBackground: false,
        })}
        <span className="text-[11px] font-medium text-zinc-400">
          Today's pipeline — Thursday, March 6
        </span>
      </div>
      <p className="mb-3 text-[11px] text-zinc-500">
        3 deals need your attention
      </p>
      <div className="space-y-2">
        {DEAL_ITEMS.map((item) => (
          <div key={item.id} className="rounded-xl bg-zinc-900 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-zinc-100">
                {item.company} — {item.value}
              </span>
              {item.urgent && (
                <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] text-red-400">
                  Urgent
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-zinc-400">{item.sub}</p>
            <p className={`mt-1 text-xs ${item.infoColor}`}>{item.info}</p>
          </div>
        ))}
      </div>
      <div className="mt-3 border-t border-zinc-800 pt-3">
        <p className="text-[11px] text-zinc-500">
          2 calls today at 11am + 3pm · 1 proposal due by EOD
        </p>
      </div>
    </div>
  );
}
