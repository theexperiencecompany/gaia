"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
  const controllerRef = useRef<WakeWordController | null>(null);
  const [state, setState] = useState<DetectorState>("idle");
  const [lastDetection, setLastDetection] = useState<DetectionEvent | null>(
    null,
  );
  const [lastScore, setLastScore] = useState<number>(0);
  const [error, setError] = useState<Error | null>(null);

  const start = useCallback(async () => {
    if (controllerRef.current) return;
    const controller = new WakeWordController(options);
    controllerRef.current = controller;
    controller.on("detection", setLastDetection);
    controller.on("state", setState);
    controller.on("score", setLastScore);
    controller.on("error", setError);
    try {
      await controller.start();
    } catch (err) {
      setError(err as Error);
      controllerRef.current = null;
    }
  }, [options]);

  const stop = useCallback(async () => {
    const controller = controllerRef.current;
    controllerRef.current = null;
    await controller?.stop();
    setState("idle");
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void start();
    return () => {
      void stop();
    };
    // The options object identity is the caller's responsibility — memoize on
    // their side. We intentionally don't depend on `options` here to avoid
    // restarting the mic on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  return { state, lastDetection, lastScore, error, start, stop };
}
