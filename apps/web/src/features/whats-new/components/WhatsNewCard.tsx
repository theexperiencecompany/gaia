"use client";

import { Button } from "@heroui/button";
import { Cancel01Icon } from "@icons";
import Image from "next/image";
import { useEffect } from "react";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { useWhatsNewStore } from "@/stores/whatsNewStore";
import { useReleases } from "../hooks/useReleases";
import { formatReleaseDate } from "../utils/formatReleaseDate";

const FALLBACK_IMAGE = "/images/whats-new-fallback.png";

export function WhatsNewCard() {
  const { releases, latest, unseen, isLoading } = useReleases();
  const dismissedUntilReleaseId = useWhatsNewStore(
    (s) => s.dismissedUntilReleaseId,
  );
  const dismissCard = useWhatsNewStore((s) => s.dismissCard);
  const openModal = useWhatsNewStore((s) => s.openModal);

  const isDismissed = !!latest && dismissedUntilReleaseId === latest.id;

  useEffect(() => {
    if (!isLoading && releases.length > 0) {
      trackEvent(ANALYTICS_EVENTS.WHATS_NEW_CARD_SHOWN, {
        unseenCount: unseen.length,
      });
    }
  }, [isLoading, releases.length, unseen.length]);

  if (isLoading || releases.length === 0 || isDismissed) return null;

  const handleOpen = () => {
    trackEvent(ANALYTICS_EVENTS.WHATS_NEW_CARD_CLICKED, {
      source: "sidebar_card",
    });
    openModal(0);
  };

  const handleDismiss = () => {
    if (!latest) return;
    trackEvent(ANALYTICS_EVENTS.WHATS_NEW_CARD_DISMISSED, {
      releaseId: latest.id,
    });
    dismissCard(latest.id);
  };

  return (
    // biome-ignore lint/a11y/useSemanticElements: outer wrapper cannot be a <button> because it contains a nested dismiss <button>
    <div
      role="button"
      tabIndex={0}
      onClick={handleOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") handleOpen();
      }}
      className="group mb-1 w-full cursor-pointer overflow-hidden rounded-2xl bg-zinc-800/50 text-left transition hover:bg-zinc-800"
    >
      {/* Hero image */}
      <div className="relative h-28 w-full overflow-hidden bg-zinc-800">
        <Image
          src={latest?.imageUrl ?? FALLBACK_IMAGE}
          alt={latest?.title ?? "What's new"}
          width={560}
          height={224}
          className="h-full w-full object-cover"
        />
        {/* Dismiss button */}
        <Button
          isIconOnly
          variant="flat"
          radius="full"
          size="sm"
          onPress={handleDismiss}
          aria-label="Dismiss what's new"
          className="absolute top-2 right-2 h-6 w-6 min-w-6 bg-zinc-900/60 text-zinc-400 hover:bg-zinc-900 hover:text-white opacity-0 group-hover:opacity-100"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          <Cancel01Icon className="h-3 w-3" />
        </Button>
      </div>

      {/* Content */}
      <div className="p-3">
        <div className="mb-1 flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
            <span className="text-xs text-zinc-400 transition group-hover:text-zinc-300">
              What&apos;s new
            </span>
          </div>
          {latest && (
            <span className="text-[11px] text-zinc-600">
              {formatReleaseDate(latest.date)}
            </span>
          )}
        </div>
        {latest && (
          <p className="text-sm font-normal leading-snug text-zinc-200 transition group-hover:text-white">
            {latest.title}
          </p>
        )}
      </div>
    </div>
  );
}
