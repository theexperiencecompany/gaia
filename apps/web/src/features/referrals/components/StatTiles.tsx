"use client";

import type { ReferralStats } from "../types";

const TILES: { key: keyof ReferralStats; label: string }[] = [
  { key: "invited", label: "Invited" },
  { key: "joined", label: "Joined" },
  { key: "upgraded", label: "Upgraded" },
  { key: "months_earned", label: "Months earned" },
];

export function StatTiles({ stats }: { stats: ReferralStats }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {TILES.map(({ key, label }) => (
        <div key={key} className="rounded-2xl bg-zinc-900/60 p-4">
          <p className="text-2xl font-semibold tabular-nums text-white">
            {stats[key]}
          </p>
          <p className="mt-0.5 text-xs text-zinc-500">{label}</p>
        </div>
      ))}
    </div>
  );
}
