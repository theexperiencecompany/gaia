"use client";

import { GaiaButton } from "@/components/shared/GaiaButton";

interface ConnectBrowserBannerProps {
  onConnect: () => void;
}

/** One-line entry point to importing more logins, shown above a non-empty
 * saved-sites list. The empty state carries its own CTA instead. */
export function ConnectBrowserBanner({ onConnect }: ConnectBrowserBannerProps) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-zinc-800 px-4 py-3">
      <p className="truncate text-sm text-zinc-300">
        Import logins from your computer's browser.
      </p>
      <GaiaButton
        size="sm"
        className="shrink-0"
        onPress={onConnect}
        variant="primary"
      >
        Import
      </GaiaButton>
    </div>
  );
}
