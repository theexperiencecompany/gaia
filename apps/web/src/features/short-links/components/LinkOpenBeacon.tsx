"use client";

import { useEffect } from "react";

import { recordShortLinkOpen } from "@/features/short-links/api/shortLinksApi";

interface LinkOpenBeaconProps {
  slug: string;
}

/**
 * Counts the link as opened from the viewer's browser, which carries the
 * session (so the owner is recognised) and the real browser (so unfurl bots
 * are). The server counts each viewer once a day, so a remount is harmless.
 */
export function LinkOpenBeacon({ slug }: LinkOpenBeaconProps) {
  useEffect(() => {
    void recordShortLinkOpen(slug);
  }, [slug]);
  return null;
}
