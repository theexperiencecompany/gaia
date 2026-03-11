import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const FOLLOWUP_ITEMS = [
  {
    id: "fq-1",
    company: "Acme Corp",
    contact: "Sarah M.",
    status: "Trial ends Friday · 6 days no contact",
    draft: "Draft: checking in before your trial wraps up...",
    urgent: true,
  },
  {
    id: "fq-2",
    company: "ByteScale",
    contact: "James T.",
    status: "9 days since demo · opened proposal 3×",
    draft: "Draft: following up on the proposal we sent...",
    urgent: false,
  },
  {
    id: "fq-3",
    company: "Momentum AI",
    contact: "Dev K.",
    status: "14 days no reply after pricing call",
    draft: "Draft: wanted to circle back on your Q2 timeline...",
    urgent: false,
  },
];

export default function FollowUpQueueCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-2">
        {getToolCategoryIcon("gmail", {
          width: 16,
          height: 16,
          showBackground: false,
        })}
        <span className="text-[11px] font-medium text-zinc-400">
          5 follow-ups queued
        </span>
      </div>
      <div className="space-y-2">
        {FOLLOWUP_ITEMS.map((item) => (
          <div key={item.id} className="rounded-xl bg-zinc-900 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-zinc-100">
                {item.company} — {item.contact}
              </span>
              {item.urgent && (
                <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] text-red-400">
                  Urgent
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-zinc-500">{item.status}</p>
            <p className="mt-1.5 text-xs italic text-zinc-400">{item.draft}</p>
          </div>
        ))}
      </div>
      <div className="mt-3 border-t border-zinc-800 pt-3">
        <p className="text-[11px] text-zinc-500">
          All drafts ready. Review and send in 1 click.
        </p>
      </div>
    </div>
  );
}
