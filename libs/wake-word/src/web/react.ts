"use client";

import { useState } from "react";
import { useWakeWordBase } from "../internal/use-wake-word-base";
import type { DetectionEvent, DetectorState } from "../types/index";
import {
  WakeWordController,
  type WakeWordControllerOptions,
} from "./controller";

export interface UseWakeWordResult {
  state: DetectorState;
  lastDetection: DetectionEvent | null;
  /** Most recent inference score (useful for UI confidence visualisation). */
  lastScore: number;
  error: Error | null;
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

/**
 * React hook for browser / Electron renderer. Starts a single controller and
 * cleans up on unmount.
 */
export function useWakeWord(
  options: WakeWordControllerOptions,
  enabled = true,
): UseWakeWordResult {
  const [lastScore, setLastScore] = useState<number>(0);
  const base = useWakeWordBase<WakeWordController>(
    () => new WakeWordController(options),
    enabled,
    (controller) => controller.on("score", setLastScore),
  );
  return { ...base, lastScore };
}
