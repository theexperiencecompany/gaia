"use client";

import { BrowserTaskHistory } from "@/features/browser/components/BrowserTaskHistory";
import { SavedLogins } from "@/features/browser/components/SavedLogins";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";

export default function BrowserSettings() {
  return (
    <SettingsPage>
      <div>
        <h2 className="text-lg font-medium text-white">Browser</h2>
        <p className="mt-1 text-sm leading-relaxed text-zinc-400">
          GAIA can browse the web on your behalf. Review what it has done and
          manage the sites it's kept session data for.
        </p>
      </div>

      <BrowserTaskHistory />
      <SavedLogins />
    </SettingsPage>
  );
}
