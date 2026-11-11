"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  createShortLink,
  fetchShareState,
  stopSharingShortLink,
} from "@/features/short-links/api/shortLinksApi";
import { copyShortLink } from "@/features/short-links/utils/copyShortLink";
import { toast } from "@/lib/toast";
import type { ShortLinkTargetType } from "@/types/features/shortLinkTypes";

const STOPPED_NOTE =
  "The link no longer opens, and GAIA won't share this again unless you copy a new link.";

const shareStateKey = (targetType: ShortLinkTargetType, targetId: string) =>
  ["short-links", "share-state", targetType, targetId] as const;

export interface ShareLink {
  /** A live link exists; false while the state is unknown. */
  isShared: boolean;
  pending: "copy" | "stop" | null;
  copyLink: () => void;
  stopSharing: () => void;
  /** Wire to the menu: the share state is only fetched while it is open. */
  onMenuOpenChange: (isOpen: boolean) => void;
}

/**
 * Copy an artifact's heygaia.link (sharing it if it isn't yet) or stop sharing
 * it, knowing whether a live link exists so "Stop sharing" is never offered for
 * something that was never shared.
 */
export function useShareLink(
  targetType: ShortLinkTargetType,
  targetId: string,
  stopWarning?: string,
): ShareLink {
  const queryClient = useQueryClient();
  const [isMenuOpen, setMenuOpen] = useState(false);
  const key = shareStateKey(targetType, targetId);

  const { data: liveUrl } = useQuery({
    queryKey: key,
    queryFn: () => fetchShareState(targetType, targetId),
    enabled: isMenuOpen,
  });

  const copy = useMutation({
    mutationFn: async () =>
      liveUrl ?? (await createShortLink(targetType, targetId)),
    onSuccess: async (url) => {
      queryClient.setQueryData(key, url);
      await copyShortLink(url);
    },
  });

  const stop = useMutation({
    mutationFn: () => stopSharingShortLink(targetType, targetId),
    onSuccess: (revoked) => {
      queryClient.setQueryData(key, null);
      if (!revoked) return;
      toast.success("Sharing stopped", {
        description: stopWarning
          ? `${STOPPED_NOTE} ${stopWarning}`
          : STOPPED_NOTE,
      });
    },
  });

  return {
    isShared: Boolean(liveUrl),
    pending: copy.isPending ? "copy" : stop.isPending ? "stop" : null,
    copyLink: () => copy.mutate(),
    stopSharing: () => stop.mutate(),
    onMenuOpenChange: setMenuOpen,
  };
}
