import { CheckmarkBadge01Icon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const PIPELINE_ITEMS = [
  {
    id: "pi-1",
    company: "Acme Corp",
    status: "Trial expires Friday",
    action: "Check-in email drafted",
    urgent: true,
  },
  {
    id: "pi-2",
    company: "ByteScale",
    status: "Silent after demo",
    action: "Follow-up with ROI calculator",
    urgent: false,
  },
  {
    id: "pi-3",
    company: "DataFlow",
    status: "Champion changed roles",
    action: "New thread recommended",
    urgent: false,
  },
];

export default function PipelineCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {getToolCategoryIcon("hubspot", {
            width: 16,
            height: 16,
            showBackground: false,
          })}
          <span className="text-[11px] font-medium text-zinc-400">
            3 deals need attention
          </span>
        </div>
      </div>
      <div className="space-y-2">
        {PIPELINE_ITEMS.map((item) => (
          <div key={item.id} className="rounded-xl bg-zinc-900 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-zinc-100">
                {item.company}
              </span>
              {item.urgent && (
                <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] text-red-400">
                  Urgent
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-zinc-500">{item.status}</p>
            <div className="mt-1.5 flex items-center gap-1.5">
              <CheckmarkBadge01Icon
                width={12}
                height={12}
                className="text-primary"
              />
              <span className="text-xs text-primary">{item.action}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
