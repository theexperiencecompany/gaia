"use client";

import { useWakeWord } from "@gaia/wake-word/web";
import { useMemo } from "react";
import { HEY_GAIA_MODEL_BUNDLE } from "../constants/models";

export interface UseHeyGaiaOptions {
  /** Enable / disable the listener. Defaults to true. */
  enabled?: boolean;
  /** Wake-word probability threshold. Default 0.6. */
  threshold?: number;
  /** Cooldown after a detection in ms. Default 1500 ms. */
  cooldownMs?: number;
}

/**
 * React hook for the GAIA web app — listens for "Hey GAIA" in the background.
 *
 *   const { state, lastDetection } = useHeyGaia({ enabled: micEnabled });
 *   useEffect(() => { if (lastDetection) openVoiceSession(); }, [lastDetection]);
 *
 * Loads ~4 MB of ONNX models once on mount (browser caches subsequently).
 * Requires `getUserMedia` permission — caller should handle the permission
 * prompt UX.
 */
export function useHeyGaia(options: UseHeyGaiaOptions = {}) {
  const { enabled = true, threshold = 0.6, cooldownMs = 1500 } = options;
  const controllerOptions = useMemo(
    () => ({
      models: HEY_GAIA_MODEL_BUNDLE,
      workletUrl: new URL(
        // The worklet ships as part of @gaia/wake-word. Bundlers that support
        // `new URL(..., import.meta.url)` (Next.js 16 Turbopack does) resolve
        // this to a hashed asset under /_next/static/.
        "@gaia/wake-word/worklet",
        import.meta.url,
      ),
      detector: { threshold, cooldownMs },
      runtime: { wasmPaths: "/wake-word/ort/" },
    }),
    [threshold, cooldownMs],
  );
  return useWakeWord(controllerOptions, enabled);
}
