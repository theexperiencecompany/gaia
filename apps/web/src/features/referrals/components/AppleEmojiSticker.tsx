"use client";

import * as m from "motion/react-m";

import { cn } from "@/lib/utils";

// Apple-style emoji rendered as a raster image (not a system glyph) so the
// ladder looks identical on every OS. The white "sticker" ring is built from
// layered drop-shadow filters — a cheap, crisp outline that hugs the emoji's
// alpha edge instead of a rectangular box.
//
// TODO: self-host these PNGs for production instead of the CDN.
const EMOJI_CDN = "https://emojicdn.elk.sh";

interface AppleEmojiStickerProps {
  emoji: string;
  /** Rendered pixel size of the emoji image (the ring extends slightly beyond). */
  size?: number;
  /** Locked milestones read as grayscale + faded. */
  dimmed?: boolean;
  /** The "next" milestone breathes — a subtle scale pulse, never a glow. */
  pulse?: boolean;
  className?: string;
}

// A tight white ring traced around the emoji's silhouette, plus one soft
// ambient shadow underneath so the sticker sits above the surface.
const STICKER_FILTER = [
  "drop-shadow(0 0 1px #fff)",
  "drop-shadow(0 0 1px #fff)",
  "drop-shadow(1px 1px 0 #fff)",
  "drop-shadow(-1px -1px 0 #fff)",
  "drop-shadow(0 4px 6px rgba(0,0,0,0.45))",
].join(" ");

export function AppleEmojiSticker({
  emoji,
  size = 44,
  dimmed = false,
  pulse = false,
  className,
}: AppleEmojiStickerProps) {
  return (
    <m.span
      className={cn("inline-flex shrink-0 select-none", className)}
      animate={pulse ? { scale: [1, 1.08, 1] } : { scale: 1 }}
      transition={
        pulse
          ? {
              duration: 2.4,
              repeat: Number.POSITIVE_INFINITY,
              ease: [0.19, 1, 0.22, 1],
            }
          : { duration: 0 }
      }
      style={{ width: size, height: size }}
    >
      {/** biome-ignore lint/performance/noImgElement: emoji CDN raster, not a Next-optimizable asset */}
      <img
        src={`${EMOJI_CDN}/${encodeURIComponent(emoji)}?style=apple`}
        alt={`${emoji} reward milestone`}
        width={size}
        height={size}
        draggable={false}
        className={cn(
          "h-full w-full object-contain transition-all duration-500",
          dimmed && "opacity-35 grayscale",
        )}
        style={{ filter: STICKER_FILTER }}
      />
    </m.span>
  );
}
