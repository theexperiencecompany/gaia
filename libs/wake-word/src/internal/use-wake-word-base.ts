"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { DetectionEvent, DetectorState } from "../types/index";

/**
 * Minimal controller contract the base hook wires up. Both the web and React
 * Native controllers structurally satisfy this (the web one additionally emits
 * `"score"`, wired by its hook via `onCreate`).
 */
export interface WakeWordControllerLike {
  on(event: "detection", cb: (payload: DetectionEvent) => void): () => void;
  on(event: "state", cb: (payload: DetectorState) => void): () => void;
  on(event: "error", cb: (payload: Error) => void): () => void;
  start(): Promise<void>;
  stop(): Promise<void>;
}

export interface WakeWordBaseResult {
  state: DetectorState;
  lastDetection: DetectionEvent | null;
  error: Error | null;
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

/**
 * Shared lifecycle hook for the web and React Native wake-word controllers.
 * Owns the controller ref, the common event wiring (detection/state/error),
 * and the `enabled`-driven start/stop effect. Platform hooks pass a controller
 * factory and may attach extra listeners through `onCreate`.
 */
export function useWakeWordBase<C extends WakeWordControllerLike>(
  createController: () => C,
  enabled: boolean,
  onCreate?: (controller: C) => void,
): WakeWordBaseResult {
  const controllerRef = useRef<C | null>(null);
  const [state, setState] = useState<DetectorState>("idle");
  const [lastDetection, setLastDetection] = useState<DetectionEvent | null>(
    null,
  );
  const [error, setError] = useState<Error | null>(null);

  const start = useCallback(async () => {
    if (controllerRef.current) return;
    // Clear any stale failure from a previous attempt before retrying.
    setError(null);
    const controller = createController();
    controllerRef.current = controller;
    controller.on("detection", setLastDetection);
    controller.on("state", setState);
    controller.on("error", setError);
    onCreate?.(controller);
    try {
      await controller.start();
      // If stop() (or a restart) ran while we were starting, this controller is
      // now detached — shut it down instead of leaving it running.
      if (controllerRef.current !== controller) {
        await controller.stop();
      }
    } catch (err) {
      setError(err as Error);
      // Only clear the ref if it still points at this (failed) controller.
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, [createController, onCreate]);

  const stop = useCallback(async () => {
    const controller = controllerRef.current;
    controllerRef.current = null;
    await controller?.stop();
    setState("idle");
    setError(null);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void start();
    return () => {
      void stop();
    };
    // Restart only when `enabled` flips — option identity is the caller's
    // responsibility (memoize upstream) to avoid restarting on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  return { state, lastDetection, error, start, stop };
}
