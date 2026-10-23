"use client";

import { Button } from "@heroui/button";
import Image from "next/image";

interface BriefLetterProps {
  headline: string;
  imageUrl?: string | null;
  isBusy?: boolean;
  onPress: () => void;
  onWarm: () => void;
}

/** The back of the folded paper, matching the unfold's panel backs. */
const PAPER_BACK =
  "linear-gradient(180deg, #c9c3b6 0%, #d9d4c8 40%, #e2ddd2 100%)";

/**
 * The edition folded in thirds and laid on the table: its masthead shows above
 * the crease, the folded-up flap covers the rest. Hover lifts the flap a touch.
 */
export function BriefLetter({
  headline,
  imageUrl,
  isBusy = false,
  onPress,
  onWarm,
}: BriefLetterProps) {
  return (
    <Button
      disableRipple
      isIconOnly
      onPress={onPress}
      onPointerEnter={onWarm}
      onPointerDown={onWarm}
      onFocus={onWarm}
      aria-label={`Open brief: ${headline}`}
      aria-busy={isBusy}
      className="group h-auto w-52 min-w-0 overflow-visible rounded-md bg-transparent p-0 transition-[scale,translate] duration-200 ease-out data-[hover=true]:-translate-y-0.5 data-[hover=true]:bg-transparent data-[pressed=true]:scale-[0.97]"
    >
      <span className="relative block aspect-[4/3] w-full rounded-md shadow-[0_1px_2px_rgba(0,0,0,0.4),0_12px_28px_-10px_rgba(0,0,0,0.7)] [perspective:600px]">
        <span className="absolute inset-x-0 top-0 h-1/2 overflow-hidden rounded-t-md bg-zinc-200">
          {imageUrl && (
            <Image
              src={imageUrl}
              alt=""
              fill
              sizes="208px"
              className="object-cover object-top"
            />
          )}
        </span>
        <span
          aria-hidden
          className="absolute inset-x-0 bottom-0 h-1/2 origin-top rounded-b-md transition-transform duration-300 ease-out group-data-[hover=true]:[transform:rotateX(14deg)]"
          style={{ background: PAPER_BACK }}
        >
          <span className="absolute inset-x-0 top-0 h-3 bg-gradient-to-b from-black/20 to-transparent" />
          <span className="absolute inset-x-0 top-0 h-px bg-white/50" />
        </span>
      </span>
    </Button>
  );
}
