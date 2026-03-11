import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const PIPELINE_ITEMS = [
  {
    id: "bd-1",
    company: "HealthTech Co",
    value: "$8,400/mo",
    hot: true,
    sub: "Inbound: website redesign + SEO",
    info: "Last contact: Today",
    infoColor: "text-primary",
  },
  {
    id: "bd-2",
    company: "Finova",
    value: "$5,200/mo",
    hot: false,
    sub: "Referral from DataFlow · Discovery call pending",
    info: "Last contact: 2 days ago",
    infoColor: "text-zinc-500",
  },
  {
    id: "bd-3",
    company: "CloudOps Inc",
    value: "$12,000 project",
    hot: false,
    sub: "RFP received · deadline Friday",
    info: "GAIA drafted proposal outline",
    infoColor: "text-primary",
  },
  {
    id: "bd-4",
    company: "Momentum 2.0",
    value: "$3,600/mo retainer",
    hot: false,
    sub: "Existing client → upsell opportunity",
    info: "Follow-up due",
    infoColor: "text-amber-400",
  },
];

export default function BDPipelineCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-1 flex items-center gap-2">
        {getToolCategoryIcon("hubspot", {
          width: 14,
          height: 14,
          showBackground: false,
        })}
        <span className="text-sm font-medium text-zinc-100">BD Pipeline</span>
      </div>
      <p className="mb-3 text-[11px] text-zinc-500">
        4 active opportunities · 2 new this week
      </p>

      <div className="space-y-2">
        {PIPELINE_ITEMS.map((item) => (
          <div key={item.id} className="rounded-xl bg-zinc-900 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-zinc-100">
                {item.company} — {item.value}
              </span>
              {item.hot && (
                <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] text-emerald-400">
                  Hot
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-zinc-500">{item.sub}</p>
            <p className={`mt-1 text-xs ${item.infoColor}`}>{item.info}</p>
          </div>
        ))}
      </div>

      <div className="mt-3 border-t border-zinc-800 pt-3">
        <p className="text-[11px] text-zinc-500">
          2 proposals due this week · $29,200 in qualified pipeline
        </p>
      </div>
    </div>
  );
}
