"use client";

import { useWakeWordNative } from "@gaia/wake-word/native";
import { useMemo } from "react";
import LiveAudioStream from "react-native-live-audio-stream";
import { HEY_GAIA_MODEL_BUNDLE } from "../constants/models";

export interface UseHeyGaiaOptions {
  enabled?: boolean;
  threshold?: number;
  cooldownMs?: number;
}

/**
 * Mobile hook. iOS needs `NSMicrophoneUsageDescription` in Info.plist and
 * the `UIBackgroundModes` audio entitlement if you want detection to run with
 * the app backgrounded. Android needs the `RECORD_AUDIO` permission and (on
 * API 34+) a foreground service of type `microphone`.
 */
export function useHeyGaia(options: UseHeyGaiaOptions = {}) {
  const { enabled = true, threshold = 0.6, cooldownMs = 1500 } = options;
  const controllerOptions = useMemo(
    () => ({
      models: HEY_GAIA_MODEL_BUNDLE,
      audio: LiveAudioStream,
      detector: { threshold, cooldownMs },
    }),
    [threshold, cooldownMs],
  );
  return useWakeWordNative(controllerOptions, enabled);
}
