"use client";

import { Button } from "@heroui/button";

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
      <Button
        size="sm"
        color="primary"
        className="shrink-0"
        onPress={onConnect}
      >
        Import
      </Button>
    </div>
  );
}
