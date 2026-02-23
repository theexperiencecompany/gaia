"use client";

import type * as React from "react";
import { useEffect, useMemo, useRef } from "react";
import { cn } from "@/lib/utils";

export type AgentState =
  | "connecting"
  | "initializing"
  | "listening"
  | "speaking"
  | "thinking";

export interface BarVisualizerProps
  extends React.HTMLAttributes<HTMLDivElement> {
  state?: AgentState;
  barCount?: number;
  mediaStream?: MediaStream | null;
  minHeight?: number;
  maxHeight?: number;
  demo?: boolean;
  centerAlign?: boolean;
}

const lerp = (start: number, end: number, factor: number) => {
  return start + (end - start) * factor;
};

const gaussian = (x: number, center: number, sigma: number) => {
  return Math.exp(-((x - center) ** 2) / (2 * sigma ** 2));
};

export const BarVisualizer = ({
  state = "listening",
  barCount = 12,
  mediaStream,
  minHeight = 10,
  maxHeight = 100,
  demo = false,
  centerAlign = true,
  className,
  ...props
}: BarVisualizerProps) => {
  const barsRef = useRef<(HTMLDivElement | null)[]>([]);
  const currentHeights = useRef<number[]>(new Array(barCount).fill(minHeight));

  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const rafId = useRef<number | null>(null);

  // Generate stable IDs for bars to avoid array index key lint
  const barIds = useMemo(
    () => Array.from({ length: barCount }, (_, i) => `bar-${i}`),
    [barCount],
  );

  useEffect(() => {
    const cleanup = () => {
      if (sourceRef.current) {
        try {
          sourceRef.current.disconnect();
        } catch (_e) {}
      }
      if (
        audioContextRef.current &&
        audioContextRef.current.state !== "closed"
      ) {
        try {
          audioContextRef.current.close();
        } catch (_e) {}
      }
    };

    if (demo || !mediaStream) return cleanup;

    const audioTracks = mediaStream.getAudioTracks();
    if (audioTracks.length === 0) return cleanup;

    const initAudio = async () => {
      try {
        const AudioCtx =
          window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext })
            .webkitAudioContext;
        const ctx = new AudioCtx();

        if (ctx.state === "suspended") {
          await ctx.resume();
        }

        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.4;

        const source = ctx.createMediaStreamSource(mediaStream);
        source.connect(analyser);

        audioContextRef.current = ctx;
        analyserRef.current = analyser;
        sourceRef.current = source;
      } catch (error) {
        console.error("Audio init failed:", error);
      }
    };

    initAudio();
    return cleanup;
  }, [mediaStream, demo]);

  useEffect(() => {
    const centerIndex = (barCount - 1) / 2;
    const sigma = barCount / 2.5;

    const animate = () => {
      let volume = 0;

      // Determine if we should be "active" (reacting to voice)
      // We react to voice in BOTH speaking (LLM) and listening (User) states
      const isActiveState = state === "speaking" || state === "listening";

      if (demo && isActiveState) {
        const time = Date.now() / 1000;
        volume = ((Math.sin(time * 3) + 1) / 2) * 0.5 + Math.random() * 0.2;
      } else if (
        isActiveState &&
        analyserRef.current &&
        audioContextRef.current?.state === "running"
      ) {
        const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(dataArray);

        let sum = 0;
        const startBin = 2;
        const endBin = Math.min(dataArray.length, 60);

        for (let i = startBin; i < endBin; i++) {
          sum += dataArray[i];
        }

        const average = sum / (endBin - startBin);
        if (average > 5) {
          volume = Math.min(1, (average / 120) * 1.4);
        }
      }

      for (let i = 0; i < barCount; i++) {
        let targetHeight = minHeight;

        if (isActiveState && volume > 0.01) {
          // Shared logic for User or LLM voice: Center-weighted Gaussian heights
          const dist = gaussian(i, centerIndex, sigma);
          const time = Date.now() / 200;
          const noise = (Math.sin(i * 0.5 + time) + 1) / 2;
          const addedHeight =
            volume * dist * (maxHeight - minHeight) * (0.8 + noise * 0.2);
          targetHeight = minHeight + addedHeight;
        } else if (state === "listening") {
          // Subtle breathing when it's quiet in listening mode
          const time = Date.now() / 1000;
          targetHeight = minHeight + Math.sin(time * 2 + i * 0.2) * 3;
        } else if (state === "thinking") {
          const time = Date.now() / 150;
          targetHeight = minHeight + (Math.sin(time) + 1) * 6;
        }

        currentHeights.current[i] = lerp(
          currentHeights.current[i],
          targetHeight,
          0.18,
        );

        if (barsRef.current[i]) {
          barsRef.current[i]!.style.height = `${currentHeights.current[i]}%`;
        }
      }

      rafId.current = requestAnimationFrame(animate);
    };

    rafId.current = requestAnimationFrame(animate);
    return () => {
      if (rafId.current) cancelAnimationFrame(rafId.current);
    };
  }, [state, demo, barCount, minHeight, maxHeight]);

  const getBarColor = () => {
    switch (state) {
      case "thinking":
        return "bg-blue-500 animate-pulse";
      case "listening":
        return "bg-primary";
      case "speaking":
        return "bg-primary";
      case "connecting":
      case "initializing":
        return "bg-primary";
      default:
        return "bg-primary";
    }
  };

  return (
    <div
      className={cn(
        "flex items-center justify-center gap-1.5 h-full w-full select-none pointer-events-none",
        className,
      )}
      {...props}
    >
      {barIds.map((id, i) => (
        <div
          key={id}
          ref={(el) => {
            barsRef.current[i] = el;
          }}
          className={cn(
            "w-2 rounded-full transition-colors duration-300 min-h-[8px]",
            getBarColor(),
          )}
          style={{
            height: `${minHeight}%`,
            transition: "background-color 0.3s ease",
          }}
        />
      ))}
    </div>
  );
};
