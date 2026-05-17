import { useCallback, useEffect, useRef, useState } from "react";
import type { DetectionEvent, DetectorState } from "../types/index.js";
import {
  WakeWordNativeController,
  type WakeWordNativeOptions,
} from "./controller.js";

export interface UseWakeWordNativeResult {
  state: DetectorState;
  lastDetection: DetectionEvent | null;
  error: Error | null;
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

/**
 * React Native hook. Mirrors the web one. Caller owns lifecycle of the audio
 * module (e.g. pause when app backgrounds without a foreground service).
 */
export function useWakeWordNative(
  options: WakeWordNativeOptions,
  enabled = true,
): UseWakeWordNativeResult {
  const controllerRef = useRef<WakeWordNativeController | null>(null);
  const [state, setState] = useState<DetectorState>("idle");
  const [lastDetection, setLastDetection] = useState<DetectionEvent | null>(
    null,
  );
  const [error, setError] = useState<Error | null>(null);

  const start = useCallback(async () => {
    if (controllerRef.current) return;
    const controller = new WakeWordNativeController(options);
    controllerRef.current = controller;
    controller.on("detection", setLastDetection);
    controller.on("state", setState);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  return { state, lastDetection, error, start, stop };
}
