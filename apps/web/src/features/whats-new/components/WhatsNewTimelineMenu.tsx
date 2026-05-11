"use client";

import { Button } from "@heroui/button";
import { PackageOpenIcon } from "@icons";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { useWhatsNewStore } from "@/stores/whatsNewStore";
import { useReleases } from "../hooks/useReleases";
import { formatReleaseDate } from "../utils/formatReleaseDate";

const VISIBLE_COUNT = 3;

interface WhatsNewTimelineMenuProps {
  onClose?: () => void;
}

export function WhatsNewTimelineMenu({ onClose }: WhatsNewTimelineMenuProps) {
  const { releases, unseen, isLoading } = useReleases();
  const openModal = useWhatsNewStore((s) => s.openModal);

  if (isLoading || releases.length === 0) return null;

  const visible = releases.slice(0, VISIBLE_COUNT);

  const handleItemClick = (idx: number) => {
    trackEvent(ANALYTICS_EVENTS.WHATS_NEW_CARD_CLICKED, {
      releaseId: visible[idx]?.id,
      index: idx,
      source: "settings_menu",
    });
    openModal(idx);
    onClose?.();
  };

  const handleViewAll = () => {
    trackEvent(ANALYTICS_EVENTS.WHATS_NEW_CARD_CLICKED, {
      source: "settings_menu_view_all",
    });
    openModal(0);
    onClose?.();
  };

  return (
    <div style={{ width: "260px" }} className="py-2">
      <p className="mb-1.5 px-3 text-[11px] font-semibold text-zinc-600">
        Recent updates
      </p>

      <ul className="px-3">
        {visible.map((release, idx) => {
          const isUnseen = unseen.some((u) => u.id === release.id);
          const isLast = idx === visible.length - 1;

          return (
            <li key={release.id} className="relative">
              <button
                type="button"
                className="group flex w-full cursor-pointer gap-x-2.5 rounded-xl px-1.5 transition-colors hover:bg-zinc-800/60"
                onClick={() => handleItemClick(idx)}
              >
                {/* Dot column */}
                <div className="relative top-2 mr-3 flex flex-col items-center">
                  <div
                    className={[
                      "z-10 mt-1 size-3 shrink-0 rounded-full border transition-transform group-hover:scale-125",
                      idx === 0
                        ? "border-primary bg-primary"
                        : "border-zinc-600 bg-zinc-600",
                    ].join(" ")}
                  />
                  {!isLast && <div className="w-px flex-1 bg-zinc-700" />}
                </div>

                {/* Content */}
                <div className="flex min-w-0 flex-1 flex-col gap-0.5 py-2 text-left">
                  <span className="flex items-center gap-1.5">
                    <span className="text-xs font-medium leading-snug text-zinc-300 transition-colors group-hover:text-white">
                      {release.title}
                    </span>
                    {isUnseen && (
                      <span className="inline-block size-1.5 shrink-0 rounded-full bg-primary" />
                    )}
                  </span>
                  <span className="text-[10px] tabular-nums text-zinc-500 transition-colors group-hover:text-zinc-400">
                    {formatReleaseDate(release.date)}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>

      {/* Footer */}
      <div className="px-3">
        <Button
          variant="light"
          size="sm"
          onPress={handleViewAll}
          startContent={<PackageOpenIcon className="size-4 shrink-0" />}
          className="justify-start text-zinc-500"
        >
          View all releases
        </Button>
      </div>
    </div>
  );
}
