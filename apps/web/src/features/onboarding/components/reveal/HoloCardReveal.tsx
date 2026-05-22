/**
 * Inline holo-card reveal shown above the chat stream. Four-state machine:
 *   idle (giftbox) → vibrating (anticipation) → bursting (scale-up + fade)
 *   → revealed (editable card with confetti)
 *
 * On hover the giftbox scales and lifts slightly, signalling it's interactive.
 * The "bursting" step double-buffers the visuals: the giftbox scales and fades
 * out while the card scales in underneath, so the transition reads as the box
 * opening rather than disappearing flatly.
 */

"use client";

import confetti from "canvas-confetti";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

import { HoloCardEditor } from "@/components/ui/holo-card/HoloCardEditor";
import type { HoloCardDisplayData } from "@/components/ui/holo-card/types";
import { HOLO_CARD_HEIGHT, HOLO_CARD_WIDTH } from "../../constants";
import type { PersonalizationData } from "../../types/websocket";

interface HoloCardRevealProps {
  personalizationData: PersonalizationData;
}

type RevealState = "idle" | "vibrating" | "bursting" | "revealed";

const GIFTBOX_SRC = "/images/onboarding/giftbox.png";

export function HoloCardReveal({ personalizationData }: HoloCardRevealProps) {
  const [revealState, setRevealState] = useState<RevealState>("idle");
  const cardWrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (revealState !== "revealed") return;
    cardWrapRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
    const confettiTimer = window.setTimeout(() => {
      const node = cardWrapRef.current;
      const origin = node
        ? (() => {
            const rect = node.getBoundingClientRect();
            return {
              x: (rect.left + rect.width / 2) / window.innerWidth,
              y: (rect.top + rect.height / 2) / window.innerHeight,
            };
          })()
        : { x: 0.5, y: 0.55 };
      confetti({
        particleCount: 160,
        spread: 80,
        startVelocity: 45,
        origin,
      });
    }, 420);
    return () => {
      window.clearTimeout(confettiTimer);
    };
  }, [revealState]);

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

  const handleGiftboxClick = () => {
    if (revealState !== "idle") return;
    setRevealState("vibrating");
  };

  const handleVibrationComplete = () => {
    setRevealState("bursting");
  };

  const handleBurstComplete = () => {
    setRevealState("revealed");
  };

  return (
    <m.div
      className="flex flex-col items-center py-2"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <div
        className="relative flex items-center justify-center"
        style={{
          width: HOLO_CARD_WIDTH,
          minHeight:
            revealState === "revealed" || revealState === "bursting"
              ? HOLO_CARD_HEIGHT
              : "auto",
        }}
      >
        <AnimatePresence>
          {revealState !== "revealed" && (
            <m.button
              key="giftbox"
              type="button"
              aria-label="Tap to reveal your personalized GAIA card"
              onClick={handleGiftboxClick}
              disabled={revealState !== "idle"}
              className={
                revealState === "bursting"
                  ? "pointer-events-none absolute inset-0 flex cursor-pointer items-center justify-center bg-transparent outline-none"
                  : "group relative flex cursor-pointer items-center justify-center bg-transparent outline-none"
              }
              style={{ perspective: 1000 }}
              exit={{ opacity: 0, transition: { duration: 0.15 } }}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={
                revealState === "vibrating"
                  ? {
                      opacity: 1,
                      scale: [1, 1.04, 1.04, 1, 1, 1, 1, 1],
                      rotate: [0, -8, 8, -10, 10, -6, 6, -3, 3, 0],
                      x: [0, -4, 4, -6, 6, -4, 4, -2, 2, 0],
                    }
                  : revealState === "bursting"
                    ? {
                        opacity: [1, 1, 0],
                        scale: [1, 1.3, 1.6],
                        rotate: 0,
                        x: 0,
                      }
                    : { opacity: 1, scale: 1, rotate: 0, x: 0 }
              }
              whileHover={
                revealState === "idle" ? { scale: 1.06, y: -6 } : undefined
              }
              whileTap={revealState === "idle" ? { scale: 0.97 } : undefined}
              transition={
                revealState === "vibrating"
                  ? { duration: 0.7, ease: "easeInOut" }
                  : revealState === "bursting"
                    ? { duration: 0.45, ease: "easeOut" }
                    : { type: "spring", stiffness: 320, damping: 22 }
              }
              onAnimationComplete={
                revealState === "vibrating"
                  ? handleVibrationComplete
                  : revealState === "bursting"
                    ? handleBurstComplete
                    : undefined
              }
            >
              <m.div
                className="relative flex flex-col items-center"
                style={{ width: HOLO_CARD_WIDTH }}
                animate={revealState === "idle" ? { y: [0, -6, 0] } : { y: 0 }}
                transition={
                  revealState === "idle"
                    ? { duration: 3, repeat: Infinity, ease: "easeInOut" }
                    : undefined
                }
              >
                <Image
                  src={GIFTBOX_SRC}
                  alt=""
                  width={1360}
                  height={952}
                  priority
                  className="h-auto w-[240px] select-none"
                  draggable={false}
                />
                {revealState === "idle" && (
                  <m.p
                    className="mt-4 text-sm text-white/80"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: [0.5, 1, 0.5] }}
                    transition={{ duration: 2.4, repeat: Infinity }}
                  >
                    Click to open
                  </m.p>
                )}
              </m.div>
            </m.button>
          )}

          {(revealState === "bursting" || revealState === "revealed") && (
            <m.div
              key="card"
              ref={cardWrapRef}
              className={
                revealState === "bursting"
                  ? "absolute inset-0 flex flex-col items-center gap-4"
                  : "flex flex-col items-center gap-4"
              }
              role="img"
              aria-label="Your personalized GAIA member card"
              initial={{ opacity: 0, scale: 0.7 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{
                type: "spring",
                stiffness: 180,
                damping: 22,
                mass: 0.9,
              }}
            >
              <HoloCardEditor
                initialData={holoCardData}
                height={HOLO_CARD_HEIGHT}
                width={HOLO_CARD_WIDTH}
              />
              <p className="text-sm text-zinc-400">
                Click to flip your personalised profile card
              </p>
            </m.div>
          )}
        </AnimatePresence>
      </div>
    </m.div>
  );
}
