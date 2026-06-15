"use client";

import * as m from "motion/react-m";

import { cn } from "@/lib/utils";

// Apple-style emoji rendered as a raster sticker. Identical visual to the
// production AppleEmojiSticker. Uses the lightweight `m` component from
// motion/react-m; the LazyMotion provider is mounted once in ReferralDemoBody.
const EMOJI_CDN = "https://emojicdn.elk.sh";

const STICKER_FILTER = [
  "drop-shadow(0 0 1px #fff)",
  "drop-shadow(0 0 1px #fff)",
  "drop-shadow(1px 1px 0 #fff)",
  "drop-shadow(-1px -1px 0 #fff)",
  "drop-shadow(0 4px 6px rgba(0,0,0,0.45))",
].join(" ");

interface DevStickerProps {
  emoji: string;
  size?: number;
  /** Locked milestones read as grayscale + faded. */
  dimmed?: boolean;
  /** The "next" milestone breathes — a subtle scale pulse, never a glow. */
  pulse?: boolean;
  /** Pop in on mount / when it unlocks. */
  pop?: boolean;
  className?: string;
}

export function DevSticker({
  emoji,
  size = 44,
  dimmed = false,
  pulse = false,
  pop = false,
  className,
}: DevStickerProps) {
  return (
    <m.span
      className={cn("inline-flex shrink-0 select-none", className)}
      initial={pop ? { scale: 0, rotate: -14 } : false}
      animate={
        pulse ? { scale: [1, 1.08, 1], rotate: 0 } : { scale: 1, rotate: 0 }
      }
      transition={
        pulse
          ? {
              duration: 2.4,
              repeat: Number.POSITIVE_INFINITY,
              ease: [0.19, 1, 0.22, 1],
            }
          : { type: "spring", stiffness: 520, damping: 18, mass: 0.7 }
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
          dimmed && "opacity-30 grayscale",
        )}
        style={{ filter: STICKER_FILTER }}
      />
    </m.span>
  );
}
