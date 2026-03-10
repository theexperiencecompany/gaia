const TIMELINE_ITEMS = [
  {
    id: "inc-1",
    time: "14:32",
    text: "Sentry: 847 errors/min spike (5× normal)",
    dotColor: "bg-red-500",
  },
  {
    id: "inc-2",
    time: "14:33",
    text: "GAIA: Linked to deploy abc1234 (feat/payments-stripe, merged 14:28)",
    dotColor: "bg-primary",
  },
  {
    id: "inc-3",
    time: "14:34",
    text: "GAIA: Alerted #oncall and @alex-m (commit author)",
    dotColor: "bg-primary",
  },
  {
    id: "inc-4",
    time: "14:35",
    text: "GitHub: Rollback PR #225 auto-drafted",
    dotColor: "bg-zinc-500",
  },
];

export default function IncidentCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-medium text-zinc-300">
          P1 Incident — /api/payments/webhook
        </span>
        <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] font-medium text-red-400">
          Active
        </span>
      </div>
      <div className="space-y-2.5">
        {TIMELINE_ITEMS.map((item) => (
          <div key={item.id} className="flex items-start gap-2.5">
            <div className="mt-1.5 flex shrink-0 flex-col items-center">
              <div className={`h-2 w-2 rounded-full ${item.dotColor}`} />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="shrink-0 font-mono text-[11px] text-zinc-500">
                {item.time}
              </span>
              <span className="text-xs text-zinc-300">{item.text}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 border-t border-zinc-700 pt-3">
        <span className="text-xs font-medium text-primary">
          Rollback PR ready — 1 click to merge
        </span>
      </div>
    </div>
  );
}
