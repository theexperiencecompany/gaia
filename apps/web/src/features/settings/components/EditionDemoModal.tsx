"use client";

import { Skeleton } from "@heroui/react";
import type { BriefingEdition } from "@shared/api/generated";
import Image from "next/image";
import { useState } from "react";

import { LetterModal } from "@/components/shared/LetterModal";
import {
  BRIEF_LETTER_MAX_WIDTH_PX,
  BRIEF_LETTER_WIDTH,
} from "@/features/briefing";
import { cn } from "@/lib/utils";

/** Built by apps/api/scripts/build_edition_thumbnails.py: each family drawing one busy sample brief. */
const demoSrc = (family: string) =>
  `/images/briefing/editions/demo/${family}.webp`;

/** A typical demo's height over width, for its intrinsic size until it loads. */
const DEMO_TYPICAL_ASPECT = 4.2;

interface EditionDemoModalProps {
  /** The edition last opened; kept while the modal closes so its exit still has a picture. */
  edition: BriefingEdition | null;
  isOpen: boolean;
  onClose: () => void;
}

/** One edition full screen, drawing a sample brief with every kind of item it can carry. */
export function EditionDemoModal({
  edition,
  isOpen,
  onClose,
}: EditionDemoModalProps) {
  const [loadedFamily, setLoadedFamily] = useState<string | null>(null);
  const isLoaded = edition !== null && loadedFamily === edition.family;
  return (
    <LetterModal
      isOpen={isOpen}
      onClose={onClose}
      ariaLabel={edition ? `${edition.name} edition sample` : "Edition sample"}
    >
      {edition && (
        <div className="relative" style={{ width: BRIEF_LETTER_WIDTH }}>
          {!isLoaded && (
            <Skeleton className="absolute inset-x-0 top-0 h-[80vh] rounded-2xl" />
          )}
          <Image
            src={demoSrc(edition.family)}
            alt={`${edition.name} edition drawing a sample brief`}
            width={BRIEF_LETTER_MAX_WIDTH_PX}
            height={Math.round(BRIEF_LETTER_MAX_WIDTH_PX * DEMO_TYPICAL_ASPECT)}
            sizes={BRIEF_LETTER_WIDTH}
            onLoad={() => setLoadedFamily(edition.family)}
            className={cn(
              "h-auto w-full transition-opacity duration-200 ease-out",
              !isLoaded && "opacity-0",
            )}
          />
        </div>
      )}
    </LetterModal>
  );
}
