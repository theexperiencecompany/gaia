"use client";

import { BrowserTaskHistory } from "@/features/browser/components/BrowserTaskHistory";
import { SavedLogins } from "@/features/browser/components/SavedLogins";
import { useBrowserUsage } from "@/features/browser/hooks/useBrowserUsage";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";

function UsageBar({ used, limit }: { used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  return (
    <div className="rounded-2xl bg-zinc-900/60 p-4">
      <div className="mb-2.5 flex items-baseline justify-between">
        <span className="text-sm text-zinc-300">Browser tasks this month</span>
        <span className="text-sm tabular-nums">
          <span className="font-semibold text-white">{used}</span>
          <span className="text-zinc-500"> / {limit}</span>
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800">
        <div
          className="h-full rounded-full bg-[#00bbff] transition-[width]"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function BrowserSettings() {
  const { used, limit, isLoading } = useBrowserUsage();

  return (
    <SettingsPage>
      <div>
        <h2 className="text-lg font-medium text-white">Browser</h2>
        <p className="mt-1 text-sm leading-relaxed text-zinc-400">
          GAIA can browse the web on your behalf. Review what it has done and
          manage the sites it's kept session data for.
        </p>
      </div>

      {!isLoading && <UsageBar used={used} limit={limit} />}

      <BrowserTaskHistory />
      <SavedLogins />
    </SettingsPage>
  );
}
