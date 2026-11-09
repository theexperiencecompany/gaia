"use client";

import { useMemo } from "react";
import type { BotPlatform } from "@/config/botPlatforms";
import { SELFHOST_BOT_PLATFORMS } from "@/features/bots/constants";
import { useBotLinks } from "@/features/bots/hooks/useBotLinks";
import { isSelfhostWeb } from "@/lib/selfhost";

/** GAIA Cloud's one-tap platforms; Slack and Discord link from Settings instead. */
const HOSTED_ONBOARDING_PLATFORMS: readonly BotPlatform[] = [
  "telegram",
  "whatsapp",
  "imessage",
];

/**
 * The platforms the platform-pick step offers: GAIA Cloud's on hosted GAIA,
 * the bots a self-hosted instance runs (undefined until its status loads).
 */
export function useOnboardingPlatforms(): readonly BotPlatform[] | undefined {
  const links = useBotLinks();
  return useMemo(() => {
    if (!isSelfhostWeb()) return HOSTED_ONBOARDING_PLATFORMS;
    return (
      links && SELFHOST_BOT_PLATFORMS.filter((platform) => links[platform])
    );
  }, [links]);
}
