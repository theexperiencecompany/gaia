"use client";

import { AnimatePresence, m, useInView } from "motion/react";
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
        className="rounded-xl bg-gradient-to-br from-zinc-800 to-zinc-700 relative overflow-hidden"
        style={{ width: 280, height: 180 }}
      >
        {/* Abstract gradient pattern simulating a generated image */}
        <div className="absolute inset-0 bg-gradient-to-br from-zinc-900/80 via-transparent to-cyan-900/30" />
        <div className="absolute top-4 left-4 right-4 h-8 rounded-lg bg-zinc-900/70 border border-zinc-700/40" />
        <div className="absolute top-16 left-4 w-24 h-2 rounded bg-zinc-600/60" />
        <div className="absolute top-20 left-4 w-16 h-2 rounded bg-zinc-700/50" />
        <div className="absolute top-28 left-4 right-4 h-14 rounded-lg bg-gradient-to-br from-zinc-800/80 to-zinc-900/60 border border-cyan-500/20" />
        <div className="absolute top-32 left-8 w-12 h-1.5 rounded bg-cyan-500/40" />
        <div className="absolute top-35 left-8 w-8 h-1.5 rounded bg-zinc-600/50" />
        {/* Cyan accent glow */}
        <div className="absolute bottom-6 right-4 w-10 h-10 rounded-full bg-cyan-500/10 blur-lg" />
        {/* Bottom overlay */}
        <div className="absolute bottom-0 left-0 right-0 px-3 py-2 bg-zinc-900/60 backdrop-blur-sm">
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
