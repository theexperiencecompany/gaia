"use client";

import type { EventProperties } from "@gaia/shared/analytics/events";
import type { ReferralCopyVariant } from "@shared/api/generated";
import { useEffect, useRef, useState } from "react";
import { track } from "@/lib/analytics";
import { getElectronAPI } from "@/lib/electron/api";
import { toast } from "@/lib/toast";
import {
  channelHref,
  type LinkChannel,
  type ShareChannel,
} from "../utils/shareTargets";

export type ShareSurface = EventProperties["referral:share_clicked"]["surface"];

const COPIED_RESET_MS = 2000;

interface UseShareLinkOptions {
  surface: ShareSurface;
  copyVariant: ReferralCopyVariant;
  url: string;
  text: string;
  emailSubject: string;
}

export function useShareLink({
  surface,
  copyVariant,
  url,
  text,
  emailSubject,
}: UseShareLinkOptions) {
  const [copied, setCopied] = useState(false);
  const [canShareNatively, setCanShareNatively] = useState(false);
  const resetTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Read after mount: neither navigator.share nor the desktop bridge exists in
  // the server pass. Electron's navigator.share is unreliable, so the desktop
  // app opens the macOS share menu through its preload bridge instead.
  useEffect(() => {
    const desktop = getElectronAPI();
    setCanShareNatively(
      desktop
        ? desktop.canShowShareSheet
        : typeof navigator.share === "function",
    );
    return () => clearTimeout(resetTimer.current);
  }, []);

  const record = (channel: ShareChannel) =>
    track("referral:share_clicked", {
      surface,
      channel,
      copy_variant: copyVariant,
    });

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      toast.error("Couldn't copy. Select the link and copy it yourself.");
      return;
    }
    record("copy");
    setCopied(true);
    clearTimeout(resetTimer.current);
    resetTimer.current = setTimeout(() => setCopied(false), COPIED_RESET_MS);
  };

  const shareNatively = async () => {
    const desktop = getElectronAPI();
    if (desktop) {
      if (await desktop.showShareSheet({ text, url })) record("native");
      return;
    }
    try {
      await navigator.share({ title: emailSubject, text, url });
    } catch (error) {
      // Closing the sheet rejects with AbortError: the user changed their mind.
      if (error instanceof DOMException && error.name === "AbortError") return;
      throw error;
    }
    record("native");
  };

  const openChannel = (channel: LinkChannel) => {
    record(channel);
    window.open(
      channelHref(channel, { text, url, emailSubject }, navigator.userAgent),
      "_blank",
      "noopener,noreferrer",
    );
  };

  return {
    canShareNatively,
    copied,
    copy,
    shareNatively,
    openChannel,
    recordQrOpened: () => record("qr"),
  };
}
