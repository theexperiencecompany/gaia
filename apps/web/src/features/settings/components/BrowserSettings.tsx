"use client";

import { BrowserTaskHistory } from "@/features/browser/components/BrowserTaskHistory";
import { SavedLogins } from "@/features/browser/components/SavedLogins";
import { useBrowserUsage } from "@/features/browser/hooks/useBrowserUsage";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";

export default function BrowserSettings() {
  const { used, limit, isLoading } = useBrowserUsage();

  return (
    <SettingsPage>
      <div>
        <h2 className="text-lg font-medium">Browser</h2>
        <p className="text-sm text-zinc-400">
          GAIA can browse the web on your behalf. Review past tasks and manage
          sites it has saved sign-in details for.
        </p>
        {!isLoading && (
          <p className="mt-2 text-xs text-zinc-500">
            Browser tasks: {used} / {limit} this month
          </p>
        )}
      </div>

      <div>
        <p className="mb-2 text-sm font-medium text-zinc-300">Task history</p>
        <p className="mb-3 text-sm text-zinc-500">
          Recent browser tasks GAIA has run for you.
        </p>
        <BrowserTaskHistory />
      </div>

      <div>
        <p className="mb-2 text-sm font-medium text-zinc-300">Saved logins</p>
        <p className="mb-3 text-sm text-zinc-500">
          Sites GAIA has saved sign-in details for.
        </p>
        <SavedLogins />
      </div>
    </SettingsPage>
  );
}
