"use client";

import { Chip, Skeleton, useOverlayState } from "@heroui/react";
import { FavouriteIcon, FullScreenIcon } from "@icons";
import type { BriefingEdition } from "@shared/api/generated";
import Image from "next/image";
import { useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { LoadError } from "@/components/shared/LoadError";
import { toneVariants } from "@/components/shared/tone";
import { EditionDemoModal } from "@/features/settings/components/EditionDemoModal";
import { SettingsSectionHeader } from "@/features/settings/components/ui/SettingsSection";
import { useBriefingEditionsSettings } from "@/features/settings/hooks/useBriefingEditionsSettings";
import { cn } from "@/lib/utils";

/** Built by apps/api/scripts/build_edition_thumbnails.py, one per daily family. */
const thumbnailSrc = (family: string) =>
  `/images/briefing/editions/${family}.webp`;

/** @icons is a solid set: the heart's own path, stroked and left unfilled, is its outline. */
const OUTLINED_HEART_CLASSES =
  "text-zinc-200 [&_path]:fill-transparent [&_path]:stroke-current [&_path]:stroke-[1.75]";

const SKELETON_KEYS = Array.from({ length: 6 }, (_, i) => `edition-${i}`);

/**
 * "Editions": every daily edition the brief can draw. Tapping a card takes it
 * out of the rotation (greyed) or puts it back; the heart makes it a
 * favourite, drawn twice as often; the corner button shows it full screen
 * drawing a sample brief.
 */
export function BriefingEditionsSettings() {
  const { editions, loadFailed, refetch, toggleOn, toggleFavourite } =
    useBriefingEditionsSettings();
  // The previewed edition outlives the close, so the letter leaves showing what it showed.
  const [previewed, setPreviewed] = useState<BriefingEdition | null>(null);
  const preview = useOverlayState();

  return (
    <section aria-label="Editions">
      <SettingsSectionHeader
        title="Editions"
        description="Tap an edition to take it out of your rotation. Favourites come up twice as often."
      />
      {loadFailed ? (
        <LoadError
          layout="inline"
          title="Couldn't load your editions."
          onRetry={refetch}
        />
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {editions
            ? editions.map((edition) => (
                <EditionCard
                  key={edition.family}
                  edition={edition}
                  onToggle={() => toggleOn(edition.family)}
                  onFavourite={() => toggleFavourite(edition.family)}
                  onPreview={() => {
                    setPreviewed(edition);
                    preview.open();
                  }}
                />
              ))
            : SKELETON_KEYS.map((key) => (
                <Skeleton key={key} className="aspect-[3/4] rounded-2xl" />
              ))}
        </div>
      )}
      <EditionDemoModal
        edition={previewed}
        isOpen={preview.isOpen}
        onClose={preview.close}
      />
    </section>
  );
}

function EditionCard({
  edition,
  onToggle,
  onFavourite,
  onPreview,
}: {
  edition: BriefingEdition;
  onToggle: () => void;
  onFavourite: () => void;
  onPreview: () => void;
}) {
  const isOff = edition.choice === "off";
  const isFavourite = edition.choice === "favourite";

  return (
    <div className="group relative">
      <button
        type="button"
        onClick={onToggle}
        aria-label={`${edition.name}: ${isOff ? "off, tap to turn on" : "on, tap to turn off"}`}
        aria-pressed={!isOff}
        className={`relative block aspect-[3/4] w-full cursor-pointer overflow-hidden rounded-2xl bg-zinc-800 outline-none transition focus-visible:ring-2 focus-visible:ring-accent active:scale-[0.97] ${isOff ? "opacity-40 grayscale" : ""}`}
      >
        <Image
          src={thumbnailSrc(edition.family)}
          alt=""
          fill
          sizes="(min-width: 640px) 220px, 45vw"
          className="object-cover object-top"
        />
      </button>
      <GaiaButton
        isIconOnly
        size="sm"
        shape="pill"
        variant="scrim"
        aria-label={
          isFavourite
            ? `Remove ${edition.name} from favourites`
            : `Favourite ${edition.name}`
        }
        aria-pressed={isFavourite}
        onPress={onFavourite}
        className="absolute top-2 right-2 z-20"
      >
        <FavouriteIcon
          size={16}
          className={isFavourite ? "text-red-500" : OUTLINED_HEART_CLASSES}
        />
      </GaiaButton>
      <GaiaButton
        isIconOnly
        size="sm"
        shape="pill"
        variant="scrim"
        aria-label={`See ${edition.name} full screen`}
        onPress={onPreview}
        className="absolute top-2 left-2 z-20 opacity-0 transition-opacity duration-200 ease-out group-hover:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
      >
        <FullScreenIcon size={16} className="text-zinc-200" />
      </GaiaButton>
      <div className="mt-2 flex items-center justify-between gap-2">
        <p
          className={`truncate text-sm font-medium ${isOff ? "text-zinc-500" : "text-zinc-200"}`}
        >
          {edition.name}
        </p>
        {/* Always laid out, so turning an edition off never moves its row. */}
        <Chip
          size="sm"
          variant="soft"
          aria-hidden={isOff ? undefined : true}
          className={toneVariants({
            tone: "muted",
            className: cn("shrink-0", !isOff && "invisible"),
          })}
        >
          <Chip.Label>Disabled</Chip.Label>
        </Chip>
      </div>
    </div>
  );
}
