"use client";

import { Skeleton } from "@heroui/skeleton";
import confetti from "canvas-confetti";
import { m } from "motion/react";
import { useRef, useState } from "react";
import { HoloCardEditor } from "@/components/ui/holo-card/HoloCardEditor";
import type { HoloCardDisplayData } from "@/components/ui/holo-card/types";
import { useOnboardingStore } from "@/stores/onboardingStore";
import { HOLO_CARD_HEIGHT, HOLO_CARD_WIDTH } from "../../constants";
import type { PersonalizationData } from "../../types/websocket";

interface HoloCardRevealProps {
  personalizationData: PersonalizationData;
}

type RevealState = "shimmer" | "vibrating" | "revealed";

export function HoloCardReveal({ personalizationData }: HoloCardRevealProps) {
  const [revealState, setRevealState] = useState<RevealState>("shimmer");
  const hasMarkedShown = useRef(false);
  const setHoloCardShown = useOnboardingStore((s) => s.setHoloCardShown);

  const holoCardData: HoloCardDisplayData = {
    house: personalizationData.house ?? "bluehaven",
    name: personalizationData.name ?? "User",
    personality_phrase:
      personalizationData.personality_phrase ?? "Curious Adventurer",
    user_bio:
      personalizationData.user_bio ??
      "A passionate individual exploring new possibilities and making an impact.",
    account_number: personalizationData.account_number
      ? `#${personalizationData.account_number}`
      : "#00000",
    member_since:
      personalizationData.member_since ??
      new Date().toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      }),
    overlay_color: personalizationData.overlay_color ?? "rgba(0,0,0,0)",
    overlay_opacity: personalizationData.overlay_opacity ?? 40,
    holo_card_id: personalizationData.holo_card_id,
  };

  const handleShimmerClick = () => {
    setRevealState("vibrating");
  };

  const handleVibrationComplete = () => {
    setRevealState("revealed");

    if (!hasMarkedShown.current) {
      hasMarkedShown.current = true;
      setHoloCardShown(true);
    }

    confetti({
      particleCount: 120,
      spread: 70,
      origin: { y: 0.6 },
    });
  };

  return (
    <m.div
      className="flex flex-col items-center"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      {revealState === "revealed" ? (
        <div
          className="flex flex-col items-center gap-4"
          role="img"
          aria-label="Your personalized GAIA member card"
        >
          <p className="text-sm text-zinc-400">Click to flip card</p>
          <HoloCardEditor
            initialData={holoCardData}
            height={HOLO_CARD_HEIGHT}
            width={HOLO_CARD_WIDTH}
          />
        </div>
      ) : (
        <m.button
          type="button"
          aria-label="Click to reveal your personalized GAIA card"
          className="group relative cursor-pointer"
          onClick={revealState === "shimmer" ? handleShimmerClick : undefined}
          animate={
            revealState === "vibrating" ? { x: [0, -4, 4, -4, 4, 0] } : { x: 0 }
          }
          transition={
            revealState === "vibrating" ? { duration: 0.3 } : undefined
          }
          onAnimationComplete={
            revealState === "vibrating" ? handleVibrationComplete : undefined
          }
        >
          {/* Shimmer card placeholder */}
          <div
            className="relative overflow-hidden rounded-2xl shadow-2xl bg-gradient-to-br from-zinc-800 to-zinc-600"
            style={{ height: HOLO_CARD_HEIGHT, width: HOLO_CARD_WIDTH }}
          >
            {/* Shimmer sweep */}
            <m.div
              className="pointer-events-none absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent"
              style={{ backgroundSize: "200% 100%" }}
              animate={{ backgroundPosition: ["200% 0", "-200% 0"] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: "linear" }}
            />

            {/* Card content skeleton */}
            <div className="flex h-full flex-col justify-between p-6">
              <div className="flex items-center justify-between">
                <Skeleton className="h-8 w-24 rounded-full" />
                <Skeleton className="h-8 w-20 rounded-full" />
              </div>
              <div className="space-y-3">
                <Skeleton className="h-10 w-48 rounded-lg" />
                <Skeleton className="h-6 w-40 rounded-lg" />
                <div className="mt-8 flex items-center justify-between">
                  <div className="space-y-2">
                    <Skeleton className="h-4 w-24 rounded" />
                    <Skeleton className="h-3 w-20 rounded" />
                  </div>
                  <Skeleton className="h-8 w-8 rounded-full" />
                </div>
              </div>
            </div>

            {/* Pulsing border */}
            <div className="pointer-events-none absolute inset-0 animate-pulse rounded-2xl ring-2 ring-primary/50 group-hover:ring-primary/80" />
          </div>

          {/* Click to reveal overlay */}
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
            <div className="animate-pulse rounded-full bg-white/20 px-8 py-4 backdrop-blur-md">
              <p className="font-serif text-2xl text-white">Click to Reveal</p>
            </div>
            <p className="text-sm text-zinc-400">Your GAIA Card awaits ✨</p>
          </div>
        </m.button>
      )}
    </m.div>
  );
}
