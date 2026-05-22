import { useWakeWordBase } from "../internal/use-wake-word-base";
import type { DetectionEvent, DetectorState } from "../types/index";
import {
  WakeWordNativeController,
  type WakeWordNativeOptions,
} from "./controller";

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
  return useWakeWordBase<WakeWordNativeController>(
    () => new WakeWordNativeController(options),
    enabled,
  );
}
