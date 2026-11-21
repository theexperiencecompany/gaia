"use client";

import { AiWebBrowsingIcon } from "@icons";

import { AppIcon } from "./AppIcon";
import type { WatchSource } from "./taskModel";

/** What a watch reads, by its mark: the app's logo, the site's icon, or the web when it has no one source. */
export function WatchIcon({
  source,
  size = 16,
}: {
  source: WatchSource;
  size?: number;
}) {
  if (source.app || source.site) {
    return <AppIcon id={source.app} site={source.site} size={size} />;
  }
  return <AiWebBrowsingIcon size={size} className="shrink-0 text-zinc-400" />;
}
