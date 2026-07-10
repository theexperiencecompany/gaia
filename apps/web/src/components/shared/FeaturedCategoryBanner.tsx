"use client";

import { Card } from "@heroui/card";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

const VISIBLE_ICONS = 4;
const ROTATE_BASE_MS = 3400;
const ROTATE_JITTER_MS = 1400;
const FADE_MS = 300;

/** Stable per-banner jitter (0..ROTATE_JITTER_MS) derived from the name, so
 * sibling banners never swap in sync without needing a random source. */
function nameJitterMs(name: string): number {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) % 997;
  return (hash / 997) * ROTATE_JITTER_MS;
}

interface FeaturedCategoryBannerProps {
  name: string;
  description: string;
  /** Icon pool — the first four render at rest, the rest rotate in one at a time. */
  icons: string[];
  onPress: () => void;
}

/**
 * Flat, icon-first category banner ("Lineup" style): four icons at rest on a
 * plain surface, one quietly swapping to another app from the pool every few
 * seconds. Deliberately no shadows, glows, gradients, or tilts.
 */
export function FeaturedCategoryBanner({
  name,
  description,
  icons,
  onPress,
}: FeaturedCategoryBannerProps) {
  const [visible, setVisible] = useState<string[]>(() =>
    icons.slice(0, VISIBLE_ICONS),
  );
  const [fadingSlot, setFadingSlot] = useState<number | null>(null);
  const swapCount = useRef(0);

  useEffect(() => {
    if (icons.length <= VISIBLE_ICONS) return;

    let fadeTimeout: ReturnType<typeof setTimeout>;
    // Jittered per-instance interval so sibling banners never swap in sync.
    const interval = setInterval(() => {
      // Walk the slots in a fixed cycle; the varying interval already keeps
      // the rotation from feeling mechanical.
      const slot = swapCount.current % VISIBLE_ICONS;
      setFadingSlot(slot);
      fadeTimeout = setTimeout(() => {
        setVisible((prev) => {
          const candidates = icons.filter((icon) => !prev.includes(icon));
          if (candidates.length === 0) return prev;
          const next = [...prev];
          next[slot] = candidates[swapCount.current % candidates.length];
          swapCount.current += 1;
          return next;
        });
        setFadingSlot(null);
      }, FADE_MS);
    }, ROTATE_BASE_MS + nameJitterMs(name));

    return () => {
      clearInterval(interval);
      clearTimeout(fadeTimeout);
    };
  }, [icons, name]);

  return (
    <Card
      isPressable
      disableRipple
      shadow="none"
      onPress={onPress}
      className="w-full rounded-3xl bg-zinc-900 outline-1 outline-zinc-800/70 transition-colors hover:bg-zinc-800/70"
    >
      <div className="flex h-36 w-full items-center justify-center gap-7">
        {visible.map((icon, slot) => (
          <Image
            key={icon}
            src={icon}
            alt=""
            width={56}
            height={56}
            className="object-contain transition-opacity duration-300"
            style={{ opacity: fadingSlot === slot ? 0 : 1 }}
          />
        ))}
      </div>
      <div className="flex w-full items-baseline justify-between px-5 pb-5">
        <h3 className="text-base font-medium text-foreground">{name}</h3>
        <span className="text-xs text-zinc-500">{description}</span>
      </div>
    </Card>
  );
}
