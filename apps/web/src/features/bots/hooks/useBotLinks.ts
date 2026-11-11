"use client";

import type { InstanceBots } from "@shared/api/generated";
import { discordInviteUrl, telegramBotUrl } from "@shared/utils";
import { useMemo } from "react";
import { useSetupStatus } from "@/features/settings/hooks/useSetupStatus";
import { isSelfhostWeb } from "@/lib/selfhost";
import { BOT_LINKS, type BotPlatform } from "../constants";

export type BotLinks = Partial<Record<BotPlatform, string>>;

/** Where this instance's own bots are reached; a platform it runs no bot on is absent. */
function instanceBotLinks(bots: InstanceBots): BotLinks {
  const links: BotLinks = {};
  if (bots.telegram_username) {
    links.telegram = telegramBotUrl(bots.telegram_username);
  }
  if (bots.discord_client_id) {
    links.discord = discordInviteUrl(bots.discord_client_id);
  }
  if (bots.slack_workspace_url) links.slack = bots.slack_workspace_url;
  return links;
}

/**
 * The link to each bot that serves this instance: GAIA Cloud's own bots on
 * hosted GAIA, the instance's (from GET /setup/status) on a self-hosted one,
 * undefined there until the status loads.
 */
export function useBotLinks(): BotLinks | undefined {
  const { data } = useSetupStatus();
  return useMemo(() => {
    if (!isSelfhostWeb()) return BOT_LINKS;
    return data ? instanceBotLinks(data.bots) : undefined;
  }, [data]);
}
