const CLIENTS = [
  {
    id: "pf-1",
    status: "green" as const,
    name: "TechCorp",
    statusText: "On track · website redesign Phase 2 · due Mar 15",
    action: "Final dev handoff Friday",
  },
  {
    id: "pf-2",
    status: "red" as const,
    name: "ByteScale",
    statusText: "3 days behind · content brief overdue",
    action: "Follow-up sent by GAIA",
  },
  {
    id: "pf-3",
    status: "green" as const,
    name: "DataFlow",
    statusText: "On track · SEO campaign month 2",
    action: "Report due Monday",
  },
  {
    id: "pf-4",
    status: "yellow" as const,
    name: "Momentum AI",
    statusText: "Scope creep risk · 14h over budget",
    action: "Needs scope conversation",
  },
  {
    id: "pf-5",
    status: "green" as const,
    name: "RetailCo",
    statusText: "On track · social media management",
    action: "Autopilot",
  },
  {
    id: "pf-6",
    status: "green" as const,
    name: "FinanceHub",
    statusText: "On track · email campaign",
    action: "Launching next week",
  },
];

const STATUS_DOT_COLORS: Record<string, string> = {
  green: "bg-emerald-400",
  red: "bg-red-400",
  yellow: "bg-amber-400",
};

export default function PortfolioBriefCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-medium text-zinc-100">
          Portfolio Brief — Thursday, March 6
        </span>
        <span className="text-[11px] text-zinc-500">6 active clients</span>
      </div>
      <div>
        {CLIENTS.map((client) => (
          <div
            key={client.id}
            className="flex items-center gap-2.5 border-b border-zinc-700/40 py-2 last:border-0"
          >
            <div
              className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT_COLORS[client.status]}`}
            />
            <span className="w-20 shrink-0 text-xs font-medium text-zinc-200">
              {client.name}
            </span>
            <span className="flex-1 text-xs text-zinc-400">
              {client.statusText}
            </span>
            <span className="shrink-0 text-[10px] text-zinc-500">
              {client.action}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-2 border-t border-zinc-800 pt-2">
        <p className="text-[11px] text-zinc-500">
          2 client calls today · 1 proposal due EOD · 3 invoices outstanding
        </p>
      </div>
    </div>
  );
}
