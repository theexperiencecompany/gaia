"use client";

import { AnimatePresence, useInView } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

// ─── Constants ────────────────────────────────────────────────────────────────

const PROMPT =
  "Create a minimalist product hero image for a SaaS dashboard, dark theme, cyan accents";

const TIMINGS = {
  shimmer: 800,
  image: 2000,
};

const ease = [0.22, 1, 0.36, 1] as const;

// ─── Shimmer ──────────────────────────────────────────────────────────────────

function Shimmer() {
  return (
    <m.div
      key="shimmer"
      className="rounded-xl bg-zinc-700/50 overflow-hidden"
      style={{ width: 280, height: 180 }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25, ease }}
    >
      <m.div
        className="h-full w-full rounded-xl bg-gradient-to-r from-transparent via-zinc-500/20 to-transparent"
        animate={{ opacity: [0.4, 0.8, 0.4] }}
        transition={{
          duration: 1.4,
          repeat: Number.POSITIVE_INFINITY,
          ease: "easeInOut",
        }}
      />
    </m.div>
  );
}

// ─── Generated Image Placeholder ─────────────────────────────────────────────

function GeneratedImage() {
  return (
    <m.div
      key="image"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4, ease }}
    >
      <div
        className="rounded-xl overflow-hidden relative"
        style={{ width: 280, height: 180 }}
      >
        <Image
          src="https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=560&q=80"
          alt="Generated: minimalist SaaS dashboard hero"
          fill
          className="object-cover"
          unoptimized
        />
        <div className="absolute bottom-0 left-0 right-0 px-3 py-2 bg-zinc-900/70 backdrop-blur-sm">
          <p className="text-xs text-zinc-400">
            minimalist · dark theme · SaaS dashboard
          </p>
        </div>
      </div>
      <p className="mt-2 text-xs text-zinc-500">Generated in 3.2s</p>
    </m.div>
  );
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function ImageGenerationDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.25 });
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  type Phase = "idle" | "shimmer" | "image";
  const [phase, setPhase] = useState<Phase>("idle");

  useEffect(() => {
    if (!inView) return;

    const add = (fn: () => void, delay: number) => {
      timersRef.current.push(setTimeout(fn, delay));
    };

    add(() => setPhase("shimmer"), TIMINGS.shimmer);
    add(() => setPhase("image"), TIMINGS.image);

    const captured = timersRef.current;
    return () => {
      for (const t of captured) clearTimeout(t);
    };
  }, [inView]);

  return (
    <div
      ref={ref}
      className="flex flex-col overflow-hidden rounded-3xl bg-zinc-900 p-5 text-left"
      style={{ minHeight: 300 }}
    >
      {/* User message bubble */}
      <m.div
        className="mb-4 flex items-end justify-end gap-3"
        initial={{ opacity: 0, y: 8 }}
        animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
        transition={{ duration: 0.35, ease }}
      >
        <div className="imessage-bubble imessage-from-me select-none text-sm max-w-[240px]">
          {PROMPT}
        </div>
        <div className="w-[35px] shrink-0" />
      </m.div>

      {/* Response area */}
      <div className="pl-[47px]">
        <AnimatePresence mode="wait">
          {phase === "shimmer" && <Shimmer />}
          {phase === "image" && <GeneratedImage />}
        </AnimatePresence>
      </div>
    </div>
  );
}
