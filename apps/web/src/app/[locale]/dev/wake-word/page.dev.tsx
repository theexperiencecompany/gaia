"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Snippet } from "@heroui/snippet";
import { Tooltip } from "@heroui/tooltip";
import {
  CheckmarkCircle02Icon,
  Mic02Icon,
  MicOff02Icon,
  WavingHand01Icon,
} from "@icons";
import { AnimatePresence, domAnimation, LazyMotion } from "motion/react";
import * as m from "motion/react-m";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useHeyGaia } from "@/features/wake-word";

interface DetectionRecord {
  id: number;
  score: number;
  detectedAt: number;
  /** Wall-clock time (epoch ms) the detection fired — for the log timestamp. */
  firedAt: number;
  speechStartedAt: number | null;
  timeToWakeMs: number | null;
}

export default function WakeWordDemoPage() {
  const [enabled, setEnabled] = useState(false);
  const [history, setHistory] = useState<DetectionRecord[]>([]);
  const [bootMs, setBootMs] = useState<number | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const speechStartedAtRef = useRef<number | null>(null);
  const lastIdRef = useRef(0);

  const { state, lastDetection, lastScore, error } = useHeyGaia({
    enabled,
    threshold: 0.6,
    cooldownMs: 1500,
  });

  // Capture "time to model ready" — from clicking Listen → state === listening.
  useEffect(() => {
    if (
      enabled &&
      startedAtRef.current &&
      state === "listening" &&
      bootMs === null
    ) {
      setBootMs(performance.now() - startedAtRef.current);
    }
    if (!enabled) {
      startedAtRef.current = null;
      setBootMs(null);
    }
  }, [enabled, state, bootMs]);

  // Track when the *current* speech segment started — the moment the score
  // first ticked above background noise. This lets us compute time-to-wake
  // (how long from "speech detected" to "wake fired").
  useEffect(() => {
    if (state !== "listening") return;
    if (lastScore > 0.15 && speechStartedAtRef.current === null) {
      speechStartedAtRef.current = performance.now();
    } else if (lastScore < 0.05) {
      speechStartedAtRef.current = null;
    }
  }, [state, lastScore]);

  // Fire on detection: record, speak response.
  useEffect(() => {
    if (!lastDetection) return;
    const id = ++lastIdRef.current;
    const detectedAt = performance.now();
    const speechStartedAt = speechStartedAtRef.current;
    const timeToWakeMs =
      speechStartedAt === null ? null : detectedAt - speechStartedAt;
    speechStartedAtRef.current = null;
    setHistory((h) =>
      [
        {
          id,
          score: lastDetection.score,
          detectedAt,
          firedAt: Date.now(),
          speechStartedAt,
          timeToWakeMs,
        },
        ...h,
      ].slice(0, 6),
    );
    // Speak the response — quick and disposable.
    try {
      if ("speechSynthesis" in globalThis) {
        const synth = globalThis.speechSynthesis;
        const utter = new SpeechSynthesisUtterance("Hey, what's up?");
        utter.rate = 1.05;
        utter.pitch = 1.05;
        const voices = synth.getVoices();
        const preferred = voices.find((v) =>
          /samantha|female|natural/i.test(v.name),
        );
        if (preferred) utter.voice = preferred;
        synth.cancel();
        synth.speak(utter);
      }
    } catch {
      // best effort
    }
  }, [lastDetection]);

  const handleToggle = useCallback(() => {
    if (!enabled) {
      startedAtRef.current = performance.now();
      setBootMs(null);
    }
    setEnabled((v) => !v);
  }, [enabled]);

  // Drive the "just fired" highlight off a ticking clock so the timer-driven
  // re-renders actually recompute the elapsed-time check (a useMemo keyed only
  // on `history` would leave it stuck true and keep the interval alive).
  const [nowMs, setNowMs] = useState(() => performance.now());
  const lastDetectedAt = history[0]?.detectedAt ?? null;
  const justFired = lastDetectedAt !== null && nowMs - lastDetectedAt < 1400;

  useEffect(() => {
    if (!justFired) return;
    const id = setInterval(() => setNowMs(performance.now()), 100);
    return () => clearInterval(id);
  }, [justFired]);

  return (
    <LazyMotion features={domAnimation}>
      <div className="min-h-screen bg-zinc-950 text-zinc-100">
        <div className="mx-auto flex max-w-5xl flex-col gap-10 px-6 py-12">
          <Header />

          <Orb state={state} score={lastScore} justFired={justFired} />

          <ControlBar
            enabled={enabled}
            state={state}
            error={error}
            onToggle={handleToggle}
          />

          <MetricsGrid
            state={state}
            enabled={enabled}
            bootMs={bootMs}
            lastScore={lastScore}
            history={history}
          />

          <DetectionLog history={history} />

          <SpecCard />
        </div>
      </div>
    </LazyMotion>
  );
}

// ---------------- subcomponents ----------------

type WakeWordState = ReturnType<typeof useHeyGaia>["state"];

function controlLabel(enabled: boolean, state: WakeWordState): string {
  if (!enabled) return "Start listening";
  if (state === "listening") return "Stop listening";
  if (state === "idle") return "Loading models...";
  return `${state}...`;
}

function formatMs(value: number | null): string {
  if (value === null) return "-";
  return `${Math.round(value)} ms`;
}

function Header() {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs uppercase tracking-[0.25em] text-zinc-500">
        wake word demo
      </span>
      <h1 className="font-serif text-5xl font-light text-zinc-50">
        Say <span className="italic">&ldquo;Hey GAIA&rdquo;</span>
      </h1>
      <p className="max-w-prose text-sm text-zinc-400">
        On-device detection runs entirely in your browser. No audio leaves your
        device. The classifier head is 122 KB, trained on 108k embedding
        windows.
      </p>
    </div>
  );
}

function Orb({
  state,
  score,
  justFired,
}: Readonly<{
  state: WakeWordState;
  score: number;
  justFired: boolean;
}>) {
  const intensity =
    state === "listening" ? Math.min(1, score * 1.5 + 0.2) : 0.05;
  const scale = justFired ? 1.18 : 1 + intensity * 0.06;
  const blur = justFired ? 60 : 26 + intensity * 18;

  return (
    <div className="relative flex h-72 items-center justify-center overflow-hidden rounded-3xl bg-zinc-900">
      {/* base hazy gradient */}
      <m.div
        className="absolute inset-0 opacity-60"
        style={{
          background:
            "radial-gradient(circle at 50% 50%, rgba(74,222,128,0.35) 0%, rgba(56,189,248,0.2) 35%, transparent 70%)",
          filter: `blur(${blur}px)`,
        }}
        animate={{ scale }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      />
      {/* moving conic gradient */}
      <m.div
        className="absolute h-[60%] w-[60%] rounded-full"
        style={{
          background:
            "conic-gradient(from 0deg, #4ade80, #38bdf8, #a855f7, #4ade80)",
          filter: "blur(28px)",
          opacity: justFired ? 0.85 : 0.35 + intensity * 0.3,
        }}
        animate={{
          rotate: state === "listening" ? 360 : 0,
          scale: justFired ? 1.3 : 1,
        }}
        transition={{
          rotate: {
            repeat: Infinity,
            duration: justFired ? 4 : 12,
            ease: "linear",
          },
          scale: { duration: 0.6, ease: [0.16, 1, 0.3, 1] },
        }}
      />
      {/* inner glassy disc */}
      <div className="relative flex h-40 w-40 items-center justify-center rounded-full bg-zinc-900/80 shadow-[0_0_60px_rgba(74,222,128,0.15),inset_0_0_30px_rgba(255,255,255,0.04)] backdrop-blur-xl">
        <AnimatePresence mode="wait" initial={false}>
          {justFired ? (
            <m.div
              key="fired"
              initial={{ scale: 0.6, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              className="flex flex-col items-center gap-1 text-emerald-300"
            >
              <WavingHand01Icon className="size-9" />
              <span className="text-xs uppercase tracking-[0.2em]">
                detected
              </span>
            </m.div>
          ) : state === "listening" ? (
            <m.div
              key="listen"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-2 text-zinc-300"
            >
              <Mic02Icon className="size-8" />
              <span className="text-xs uppercase tracking-[0.2em] text-zinc-500">
                listening
              </span>
            </m.div>
          ) : (
            <m.div
              key="off"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-2 text-zinc-500"
            >
              <MicOff02Icon className="size-8" />
              <span className="text-xs uppercase tracking-[0.2em]">
                {state === "idle" ? "idle" : state}
              </span>
            </m.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function ControlBar({
  enabled,
  state,
  error,
  onToggle,
}: Readonly<{
  enabled: boolean;
  state: WakeWordState;
  error: Error | null;
  onToggle: () => void;
}>) {
  const label = controlLabel(enabled, state);
  return (
    <div className="flex flex-wrap items-center gap-4">
      <Button
        size="lg"
        color={enabled ? "danger" : "primary"}
        startContent={
          enabled ? (
            <MicOff02Icon className="size-4" />
          ) : (
            <Mic02Icon className="size-4" />
          )
        }
        onPress={onToggle}
      >
        {label}
      </Button>

      <div className="flex items-center gap-2">
        <Tooltip content="Detector status">
          <Chip
            variant="flat"
            color={state === "listening" ? "success" : "default"}
            size="sm"
          >
            {state}
          </Chip>
        </Tooltip>

        {state === "listening" && (
          <Chip variant="flat" color="primary" size="sm">
            threshold 0.60
          </Chip>
        )}

        {error && (
          <Chip variant="flat" color="danger" size="sm">
            {error.message}
          </Chip>
        )}
      </div>

      <p className="ml-auto max-w-sm text-xs text-zinc-500">
        Try: &ldquo;<span className="text-zinc-300">Hey GAIA</span>&rdquo;. Then
        try a confuser like &ldquo;Hey Google&rdquo; or &ldquo;Hey Kayla&rdquo;
        and confirm it doesn&rsquo;t fire.
      </p>
    </div>
  );
}

function MetricsGrid({
  state,
  enabled,
  bootMs,
  lastScore,
  history,
}: Readonly<{
  state: WakeWordState;
  enabled: boolean;
  bootMs: number | null;
  lastScore: number;
  history: DetectionRecord[];
}>) {
  const lastDetection = history[0];
  const lastTimeToWake = lastDetection?.timeToWakeMs ?? null;
  const avgTimeToWake = useMemo(() => {
    const samples = history
      .map((h) => h.timeToWakeMs)
      .filter((v): v is number => v !== null);
    if (samples.length === 0) return null;
    return samples.reduce((a, b) => a + b, 0) / samples.length;
  }, [history]);

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <MetricCard
        label="model boot"
        value={formatMs(bootMs)}
        hint="mic permission + ONNX load"
      />
      <MetricCard
        label="last score"
        value={enabled ? lastScore.toFixed(3) : "-"}
        hint="probability in [0, 1]"
        accent={state === "listening" && lastScore > 0.4}
      />
      <MetricCard
        label="last time-to-wake"
        value={formatMs(lastTimeToWake)}
        hint="speech onset to detection"
      />
      <MetricCard
        label="avg time-to-wake"
        value={formatMs(avgTimeToWake)}
        hint={`over ${history.length} detection${history.length === 1 ? "" : "s"}`}
      />
    </div>
  );
}

function MetricCard({
  label,
  value,
  hint,
  accent,
}: Readonly<{
  label: string;
  value: string;
  hint: string;
  accent?: boolean;
}>) {
  return (
    <div className="rounded-2xl bg-zinc-900 p-4">
      <div className="flex flex-col gap-1">
        <span className="text-[0.65rem] uppercase tracking-[0.2em] text-zinc-500">
          {label}
        </span>
        <span
          className={`font-mono text-2xl font-light ${
            accent ? "text-emerald-300" : "text-zinc-100"
          }`}
        >
          {value}
        </span>
        <span className="text-xs text-zinc-500">{hint}</span>
      </div>
    </div>
  );
}

function DetectionLog({ history }: Readonly<{ history: DetectionRecord[] }>) {
  return (
    <div className="rounded-2xl bg-zinc-900 p-4">
      <div className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <span className="text-xs uppercase tracking-[0.2em] text-zinc-500">
            detection log
          </span>
          <span className="font-mono text-xs text-zinc-500">
            {history.length} / 6
          </span>
        </div>
        {history.length === 0 ? (
          <p className="font-mono text-sm text-zinc-500">No detections yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {history.map((h) => (
              <li
                key={h.id}
                className="flex items-center gap-3 rounded-lg bg-zinc-900/60 px-3 py-2 font-mono text-sm"
              >
                <CheckmarkCircle02Icon className="size-4 shrink-0 text-emerald-400" />
                <span className="text-zinc-100">#{h.id}</span>
                <span className="text-zinc-400">
                  score {h.score.toFixed(3)}
                </span>
                <span className="text-zinc-400">
                  {h.timeToWakeMs === null
                    ? "no onset"
                    : `${Math.round(h.timeToWakeMs)} ms`}
                </span>
                <span className="ml-auto text-zinc-500">
                  {new Date(h.firedAt).toLocaleTimeString(undefined, {
                    hour12: false,
                  })}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function SpecCard() {
  return (
    <div className="rounded-2xl bg-zinc-900 p-4">
      <div className="flex flex-col gap-4">
        <span className="text-xs uppercase tracking-[0.2em] text-zinc-500">
          under the hood
        </span>
        <div className="grid gap-3 md:grid-cols-2">
          <SpecRow label="classifier head" value="122 KB ONNX (Conv1D)" />
          <SpecRow
            label="frozen backbone"
            value="openWakeWord mel + embedding"
          />
          <SpecRow label="trained on" value="18.6k positives + 25k negatives" />
          <SpecRow label="runtime" value="onnxruntime-web (WASM-SIMD)" />
          <SpecRow label="positive recall" value="97.7% (held-out)" />
          <SpecRow label="real-speech FPR" value="0.0% on LibriSpeech" />
          <SpecRow label="per-frame inference" value="~1.6 ms (Node CPU)" />
          <SpecRow label="warmup" value="~2 s after listening starts" />
        </div>
        <Snippet
          variant="bordered"
          size="sm"
          className="bg-zinc-900 font-mono text-xs"
          hideSymbol
        >
          {`import { useHeyGaia } from "@/features/wake-word";`}
        </Snippet>
      </div>
    </div>
  );
}

function SpecRow({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="flex items-baseline justify-between gap-3 rounded-lg bg-zinc-900/60 px-3 py-2">
      <span className="text-xs text-zinc-500">{label}</span>
      <span className="font-mono text-xs text-zinc-200">{value}</span>
    </div>
  );
}
