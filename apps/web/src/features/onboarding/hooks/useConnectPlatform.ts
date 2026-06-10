/**
 * Shared platform-connect logic for onboarding. Each platform button just
 * opens that platform's public bot link in a new tab (Telegram/WhatsApp deep
 * link, Slack/Discord install page) and dispatches `platformConnected` so the
 * stage advances. Both the active platforms stage and the post-ack accordion
 * share this wiring via the returned `connect`/`skip` callbacks.
 */

"use client";

import { type Dispatch, useCallback } from "react";
import { BOT_LINKS, type BotPlatform } from "@/features/bots/constants";
import type { Action } from "../state/types";

interface UseConnectPlatformReturn {
  connect: (platform: string) => void;
  skip: () => void;
}

export function useConnectPlatform(
  dispatch: Dispatch<Action>,
): UseConnectPlatformReturn {
  const connect = useCallback(
    (platform: string) => {
      const url = BOT_LINKS[platform as BotPlatform];
      if (url) window.open(url, "_blank");
      dispatch({ type: "platformConnected", platform });
    },
    [dispatch],
  );

  const skip = useCallback(() => {
    dispatch({ type: "skipPlatforms" });
  }, [dispatch]);

  return { connect, skip };
}
