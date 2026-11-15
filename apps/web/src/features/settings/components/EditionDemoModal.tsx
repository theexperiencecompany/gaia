"use client";

import { Skeleton } from "@heroui/skeleton";
import type { BriefingEdition } from "@shared/api/generated";
import Image from "next/image";
import { useState } from "react";

import { LetterModal } from "@/components/shared/LetterModal";
import { cn } from "@/lib/utils";

/** Built by apps/api/scripts/build_edition_thumbnails.py: each family drawing one busy sample brief. */
const demoSrc = (family: string) =>
  `/images/briefing/editions/demo/${family}.webp`;

/** The demo's drawn width, and a typical height for its placeholder box until it loads. */
const DEMO_WIDTH = 572;
const DEMO_TYPICAL_HEIGHT = 2400;

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
        <div className="relative">
          {!isLoaded && (
            <Skeleton className="absolute inset-x-0 top-0 h-[80vh] rounded-2xl" />
          )}
          <Image
            src={demoSrc(edition.family)}
            alt={`${edition.name} edition drawing a sample brief`}
            width={DEMO_WIDTH}
            height={DEMO_TYPICAL_HEIGHT}
            sizes="(max-width: 640px) 100vw, 572px"
            onLoad={() => setLoadedFamily(edition.family)}
            className={cn(
              "mx-auto h-auto w-full max-w-[572px] transition-opacity duration-200 ease-out",
              !isLoaded && "opacity-0",
            )}
          />
        </div>
      )}
    </LetterModal>
  );
}
