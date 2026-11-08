"use client";

import { BOT_PLATFORM_ICONS, BOT_PLATFORM_LABELS } from "@/config/botPlatforms";
import { isSelfhostWeb } from "@/lib/selfhost";
import {
  BOTS,
  type BotConfig,
  SELFHOST_BOT_COPY,
  SELFHOST_BOT_PLATFORMS,
  SELFHOST_BOTS_DOCS_URL,
} from "../constants";
import { useBotLinks } from "./useBotLinks";

/**
 * The Bots page's cards: GAIA Cloud's bots on hosted GAIA; on a self-hosted
 * instance one card per bot it can run, linking to its own bot or naming the
 * command that adds it.
 */
export function useBotCards(): BotConfig[] {
  const links = useBotLinks();
  if (!isSelfhostWeb()) return BOTS;
  return SELFHOST_BOT_PLATFORMS.map((platform): BotConfig => {
    const href = links?.[platform];
    const copy = SELFHOST_BOT_COPY[platform];
    return {
      id: platform,
      icon: BOT_PLATFORM_ICONS[platform],
      name: BOT_PLATFORM_LABELS[platform],
      description: copy.description,
      primaryAction: href
        ? { label: copy.actionLabel, href, external: true }
        : undefined,
      secondaryAction: {
        label: "Read the Docs",
        href: SELFHOST_BOTS_DOCS_URL,
        external: true,
      },
      setupCommand: links && !href ? `gaia bots add ${platform}` : undefined,
    };
  });
}
