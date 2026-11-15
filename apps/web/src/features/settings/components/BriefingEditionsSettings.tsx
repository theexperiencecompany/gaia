"use client";

import { Button } from "@heroui/button";
import { Card } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";
import { FavouriteIcon } from "@icons";
import type { BriefingEdition } from "@shared/api/generated";
import Image from "next/image";
import { useBriefingEditionsSettings } from "@/features/settings/hooks/useBriefingEditionsSettings";

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
      <Card
        isPressable
        onPress={onToggle}
        aria-label={`${edition.name}: ${isOff ? "off, tap to turn on" : "on, tap to turn off"}`}
        aria-pressed={!isOff}
        className={`aspect-[3/4] w-full bg-zinc-800 transition ${isOff ? "opacity-40 grayscale" : ""}`}
      >
        <Image
          src={thumbnailSrc(edition.family)}
          alt=""
          fill
          sizes="(min-width: 640px) 220px, 45vw"
          className="object-cover object-top"
        />
      </Card>
      <Button
        isIconOnly
        size="sm"
        radius="full"
        variant="flat"
        aria-label={
          isFavourite
            ? `Remove ${edition.name} from favourites`
            : `Favourite ${edition.name}`
        }
        aria-pressed={isFavourite}
        onPress={onFavourite}
        className="absolute top-2 right-2 z-20 bg-black/50 backdrop-blur"
      >
        <FavouriteIcon
          size={16}
          className={isFavourite ? "text-red-500" : OUTLINED_HEART_CLASSES}
        />
      </Button>
      <div className="mt-2 flex items-center justify-between gap-2">
        <p
          className={`truncate text-sm font-medium ${isOff ? "text-zinc-500" : "text-zinc-200"}`}
        >
          {edition.name}
        </p>
        {isOff && (
          <Chip size="sm" variant="flat" className="shrink-0 text-zinc-400">
            Disabled
          </Chip>
        )}
      </div>
    </div>
  );
}
