"use client";

import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useMemo, useRef, useState } from "react";
import { EASE_OUT_QUART } from "../constants/motion";

const CHAR_EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];
const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

const SCENE_1_TEXT = "Welcome to GAIA";
const CHAR_DURATION = 0.9;
const CHAR_STAGGER = 0.025;
const SCENE_1_HOLD = 0.45;
const SCENE_1_OUT = 0.3;

const SCENE_2_TEXT = "Your personal AI assistant";
const WORD_DURATION = 0.6;
const WORD_STAGGER = 0.1;
const SCENE_2_HOLD = 0.35;
const SCENE_2_OUT = 0.3;

const SCENE_3_HANDOFF = 0.08;
const INTRO_EXIT_DURATION = 0.9;

const sumScene1 = () => {
  const lastChar = (SCENE_1_TEXT.length - 1) * CHAR_STAGGER + CHAR_DURATION;
  return lastChar + SCENE_1_HOLD + SCENE_1_OUT;
};

const sumScene2 = () => {
  const words = SCENE_2_TEXT.split(/\s+/).filter(Boolean);
  const lastWord = (words.length - 1) * WORD_STAGGER + WORD_DURATION;
  return lastWord + SCENE_2_HOLD + SCENE_2_OUT;
};

interface OnboardingIntroProps {
  onComplete: () => void;
}

export function OnboardingIntro({ onComplete }: OnboardingIntroProps) {
  const [scene, setScene] = useState<1 | 2 | 3>(1);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const scene1Duration = useMemo(sumScene1, []);
  const scene2Duration = useMemo(sumScene2, []);

  useEffect(() => {
    const audio = new Audio("/audio/onboarding-intro.mp3");
    audio.preload = "auto";
    audio.volume = 0.7;
    audioRef.current = audio;
    return () => {
      audioRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (scene !== 2) return;
    const audio = audioRef.current;
    if (!audio) return;

    const events = [
      "pointerdown",
      "pointermove",
      "click",
      "keydown",
      "touchstart",
      "scroll",
    ] as const;
    let played = false;
    const removeListeners = () => {
      for (const evt of events) {
        window.removeEventListener(evt, handler, { capture: true });
      }
    };
    const tryPlay = () => {
      if (played) return;
      played = true;
      audio.play().catch(() => {
        played = false;
      });
      removeListeners();
    };
    const handler = () => tryPlay();
    for (const evt of events) {
      window.addEventListener(evt, handler, {
        passive: true,
        capture: true,
      });
    }
    tryPlay();

    return removeListeners;
  }, [scene]);

  useEffect(() => {
    const t1 = window.setTimeout(() => setScene(2), scene1Duration * 1000);
    const t2 = window.setTimeout(
      () => setScene(3),
      (scene1Duration + scene2Duration) * 1000,
    );
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [scene1Duration, scene2Duration]);

  useEffect(() => {
    if (scene !== 3) return;
    const handoff = window.setTimeout(
      () => onCompleteRef.current(),
      SCENE_3_HANDOFF * 1000,
    );
    return () => window.clearTimeout(handoff);
  }, [scene]);

  return (
    <m.div
      aria-hidden
      className="pointer-events-none fixed inset-0 z-[60] flex items-center justify-center overflow-hidden bg-black"
      initial={{ opacity: 1 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, filter: "blur(8px)" }}
      transition={{ duration: INTRO_EXIT_DURATION, ease: EASE_OUT_QUART }}
    >
      <m.div
        className="absolute inset-0 bg-center bg-cover"
        style={{
          backgroundImage: "url('/images/wallpapers/bands_gradient_black.png')",
        }}
        initial={{ opacity: 0, scale: 1.04 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 1.4, ease: EASE_OUT_QUART }}
      />

      <div
        className="relative z-10 px-8 text-center text-white"
        style={{
          fontFamily: "var(--font-aeonik), system-ui, sans-serif",
          fontWeight: 700,
          letterSpacing: "-0.04em",
          lineHeight: 1.05,
        }}
      >
        <AnimatePresence mode="wait">
          {scene === 1 && (
            <m.h1
              key="scene-1"
              className="m-0 flex flex-wrap items-center justify-center"
              style={{ fontSize: "clamp(48px, 9vw, 120px)" }}
              exit={{ opacity: 0, filter: "blur(6px)" }}
              transition={{ duration: SCENE_1_OUT, ease: EASE_OUT_QUART }}
            >
              {SCENE_1_TEXT.split("").map((char, i) => (
                <m.span
                  // biome-ignore lint/suspicious/noArrayIndexKey: char positions are stable
                  key={i}
                  className="inline-block whitespace-pre"
                  initial={{ opacity: 0, y: 16, filter: "blur(12px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  transition={{
                    duration: CHAR_DURATION,
                    delay: i * CHAR_STAGGER,
                    ease: CHAR_EASE,
                  }}
                >
                  {char === " " ? " " : char}
                </m.span>
              ))}
            </m.h1>
          )}

          {scene === 2 && (
            <m.h1
              key="scene-2"
              className="m-0 flex flex-wrap items-center justify-center gap-x-[0.28em]"
              style={{
                fontSize: "clamp(22px, 3.2vw, 44px)",
                letterSpacing: "-0.02em",
                fontWeight: 500,
              }}
              exit={{ opacity: 0, filter: "blur(6px)" }}
              transition={{ duration: SCENE_2_OUT, ease: EASE_OUT_QUART }}
            >
              {SCENE_2_TEXT.split(/\s+/)
                .filter(Boolean)
                .map((word, i) => (
                  <m.span
                    // biome-ignore lint/suspicious/noArrayIndexKey: word positions are stable
                    key={i}
                    className="inline-block"
                    initial={{ opacity: 0, y: 8, filter: "blur(8px)" }}
                    animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                    transition={{
                      duration: WORD_DURATION,
                      delay: i * WORD_STAGGER,
                      ease: APPLE_EASE,
                    }}
                  >
                    {word}
                  </m.span>
                ))}
            </m.h1>
          )}
        </AnimatePresence>
      </div>
    </m.div>
  );
}
