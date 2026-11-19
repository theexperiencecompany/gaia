"use client";

import { Skeleton } from "@heroui/react";
import { FavouriteIcon } from "@icons";
import type { BriefingEdition } from "@shared/api/generated";
import Image from "next/image";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { useBriefingEditionsSettings } from "@/features/settings/hooks/useBriefingEditionsSettings";

/** Built by apps/api/scripts/build_edition_thumbnails.py, one per daily family. */
const thumbnailSrc = (family: string) =>
  `/images/briefing/editions/${family}.webp`;

const SKELETON_KEYS = Array.from({ length: 6 }, (_, i) => `edition-${i}`);

/**
 * "Editions": every daily edition the brief can draw. Tapping a card takes it
 * out of the rotation (greyed) or puts it back; the heart makes it a
 * favourite, drawn twice as often.
 */
export function BriefingEditionsSettings() {
  const { editions, loadFailed, toggleOn, toggleFavourite } =
    useBriefingEditionsSettings();

  return (
    <section aria-label="Editions">
      <p className="mb-2 text-sm font-medium text-zinc-300">Editions</p>
      <p className="mb-3 text-sm text-zinc-500">
        {loadFailed
          ? "Couldn't load your editions. Reload the page to try again."
          : "Tap an edition to take it out of your rotation. Favourites come up twice as often."}
      </p>
      {!loadFailed && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {editions
            ? editions.map((edition) => (
                <EditionCard
                  key={edition.family}
                  edition={edition}
                  onToggle={() => toggleOn(edition.family)}
                  onFavourite={() => toggleFavourite(edition.family)}
                />
              ))
            : SKELETON_KEYS.map((key) => (
                <Skeleton key={key} className="aspect-[3/4] rounded-2xl" />
              ))}
        </div>
      )}
    </section>
  );
}

function EditionCard({
  edition,
  onToggle,
  onFavourite,
}: {
  edition: BriefingEdition;
  onToggle: () => void;
  onFavourite: () => void;
}) {
  const isOff = edition.choice === "off";
  const isFavourite = edition.choice === "favourite";

  return (
    <div className="relative">
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
          className={isFavourite ? "text-red-500" : "text-zinc-300"}
        />
      </GaiaButton>
      <p
        className={`mt-2 text-sm font-medium ${isOff ? "text-zinc-500" : "text-zinc-200"}`}
      >
        {edition.name}
      </p>
    </div>
  );
}
