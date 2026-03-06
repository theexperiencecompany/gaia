import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const METRICS = [
  { label: "MRR", value: "$47,200", change: "+24%", positive: true },
  { label: "Customers", value: "312", change: "+18", positive: true },
  { label: "Churn", value: "1.2%", change: "0.3%", positive: true },
];

export default function InvestorMetricsCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-2">
        {getToolCategoryIcon("googlesheets", {
          width: 16,
          height: 16,
          showBackground: false,
        })}
        <span className="text-[11px] font-medium text-zinc-400">
          Live metrics pulled from Google Sheets
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2.5">
        {METRICS.map((m) => (
          <div key={m.label} className="rounded-xl bg-zinc-900 p-2.5">
            <p className="text-[10px] text-zinc-500">{m.label}</p>
            <p className="text-sm font-medium text-white">{m.value}</p>
            <p className="mt-0.5 text-[10px] text-emerald-400">
              {m.positive
                ? m.label === "Churn"
                  ? `\u2193${m.change}`
                  : m.change
                : m.change}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
