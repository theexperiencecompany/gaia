"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  createShortLink,
  fetchShareState,
  rotateLink,
  stopSharingShortLink,
  updateLinkSettings,
} from "@/features/short-links/api/shortLinksApi";
import { copyShortLink } from "@/features/short-links/utils/copyShortLink";
import { toast } from "@/lib/toast";
import type {
  LinkSettings,
  ShortLinkResponse,
  ShortLinkTargetType,
} from "@/types/features/shortLinkTypes";

const STOPPED_NOTE =
  "The link no longer opens, and GAIA won't share this again unless you copy a new link.";

const shareStateKey = (targetType: ShortLinkTargetType, targetId: string) =>
  ["short-links", "share-state", targetType, targetId] as const;

export interface ShareLink {
  /** The live link, null when not shared, undefined while the state is unknown. */
  link: ShortLinkResponse | null | undefined;
  /** A live link exists; false while the state is unknown. */
  isShared: boolean;
  pending: "copy" | "stop" | null;
  copyLink: () => void;
  stopSharing: () => void;
  /** Wire to the menu: the share state is only fetched while it or the settings are open. */
  onMenuOpenChange: (isOpen: boolean) => void;
  isSettingsOpen: boolean;
  openSettings: () => void;
  closeSettings: () => void;
  /** Apply settings to the live link, or mint one with them when none is live. */
  saveSettings: (settings: LinkSettings) => void;
  isSaving: boolean;
  /** Replace the live link with a new URL; the old one stops opening. */
  rotate: () => void;
  isRotating: boolean;
}

/**
 * Copy an artifact's heygaia.link (sharing it if it isn't yet), stop sharing
 * it, or change who it opens for, knowing whether a live link exists so "Stop
 * sharing" is never offered for something that was never shared.
 */
export function useShareLink(
  targetType: ShortLinkTargetType,
  targetId: string,
  stopWarning?: string,
): ShareLink {
  const queryClient = useQueryClient();
  const [isMenuOpen, setMenuOpen] = useState(false);
  const [isSettingsOpen, setSettingsOpen] = useState(false);
  const key = shareStateKey(targetType, targetId);
  const remember = (link: ShortLinkResponse | null) =>
    queryClient.setQueryData(key, link);

  const { data: link } = useQuery({
    queryKey: key,
    queryFn: () => fetchShareState(targetType, targetId),
    enabled: isMenuOpen || isSettingsOpen,
  });

  const copy = useMutation({
    mutationFn: async () =>
      link ?? (await createShortLink(targetType, targetId)),
    onSuccess: async (copied) => {
      remember(copied);
      await copyShortLink(copied);
    },
  });

  const stop = useMutation({
    mutationFn: () => stopSharingShortLink(targetType, targetId),
    onSuccess: (revoked) => {
      remember(null);
      if (!revoked) return;
      toast.success("Sharing stopped", {
        description: stopWarning
          ? `${STOPPED_NOTE} ${stopWarning}`
          : STOPPED_NOTE,
      });
    },
  });

  const save = useMutation({
    mutationFn: (settings: LinkSettings) =>
      link
        ? updateLinkSettings(link.slug, settings)
        : createShortLink(targetType, targetId, settings),
    onSuccess: (saved) => {
      remember(saved);
      setSettingsOpen(false);
      toast.success("Share settings saved");
    },
  });

  const rotation = useMutation({
    mutationFn: (slug: string) => rotateLink(slug),
    onSuccess: (rotated) => {
      remember(rotated);
      toast.success("New link ready", {
        description: "The old link no longer opens.",
      });
    },
  });

  return {
    link,
    isShared: Boolean(link),
    pending: copy.isPending ? "copy" : stop.isPending ? "stop" : null,
    copyLink: () => copy.mutate(),
    stopSharing: () => stop.mutate(),
    onMenuOpenChange: setMenuOpen,
    isSettingsOpen,
    openSettings: () => setSettingsOpen(true),
    closeSettings: () => setSettingsOpen(false),
    saveSettings: (settings) => save.mutate(settings),
    isSaving: save.isPending,
    rotate: () => {
      if (link) rotation.mutate(link.slug);
    },
    isRotating: rotation.isPending,
  };
}
