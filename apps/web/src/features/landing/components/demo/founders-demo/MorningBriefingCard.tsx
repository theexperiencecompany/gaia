import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const BRIEFING_ITEMS = [
  {
    id: "bi-1",
    icon: "gmail",
    text: "4 urgent emails — Sequoia wants to schedule next week",
  },
  {
    id: "bi-2",
    icon: "googlecalendar",
    text: "3 meetings today — board sync at 2pm needs your Q4 deck",
  },
  {
    id: "bi-3",
    icon: "slack",
    text: "2 Slack threads in #product need your input",
  },
  {
    id: "bi-4",
    icon: "github",
    text: "Deployment blocker flagged by lead engineer",
  },
];

export default function MorningBriefingCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-[11px] font-medium text-zinc-400">
          Prioritized by urgency
        </span>
      </div>
      <div className="space-y-2.5">
        {BRIEFING_ITEMS.map((item) => (
          <div key={item.id} className="flex items-start gap-2.5 text-sm">
            <div className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
              {getToolCategoryIcon(item.icon, {
                width: 14,
                height: 14,
                showBackground: false,
              })}
            </div>
            <span className="text-zinc-300">{item.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
