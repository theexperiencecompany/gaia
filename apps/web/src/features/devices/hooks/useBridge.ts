"use client";

import type { AddOptions } from "@shared/bridge-core/config-builders";
import type {
  BridgeInvokeResult,
  BridgeStatus,
  DeviceServerView,
} from "@shared/bridge-core/ipc.types";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getElectronAPI } from "@/lib/electron/api";
import { toast } from "@/lib/toast";

const OFFLINE_STATUS: BridgeStatus = {
  paired: false,
  running: false,
  deviceId: null,
};

/** Unwrap a bridge envelope, throwing the server-supplied message so the
 * caller's catch can surface the real reason (incl. the 409 device-cap text)
 * instead of a generic failure. */
function unwrap<T>(result: BridgeInvokeResult<T>): T {
  if (result.ok) return result.value;
  throw new Error(result.error.message);
}

/** Which in-flight action owns the card's busy state, so only the pressed
 * control shows a spinner (pairing vs. toggling the tunnel vs. a server op). */
export type BridgeAction = "pair" | "toggle" | "server";

/**
 * Drives the desktop-hosted device bridge from the renderer over
 * `window.api.bridge`. Owns the live status (seeded once, then pushed from the
 * main process), the exposed server list, and the pair/toggle/add/remove
 * actions. `available` is false outside the desktop app, so the web build can
 * import this without a runtime `window.api`.
 */
export function useBridge() {
  const api = useMemo(() => getElectronAPI()?.bridge ?? null, []);
  const [status, setStatus] = useState<BridgeStatus>(OFFLINE_STATUS);
  const [servers, setServers] = useState<DeviceServerView[]>([]);
  const [busy, setBusy] = useState<BridgeAction | null>(null);

  const loadServers = useCallback(async () => {
    if (!api) return;
    const result = await api.listServers();
    // A failed list is non-fatal to the card: keep the last known servers and
    // let the next successful action refresh them.
    if (result.ok) setServers(result.value);
  }, [api]);

  // Seed status once, then follow the main process's pushed updates (pair,
  // start, stop, and the revoke/logout teardown all emit here).
  useEffect(() => {
    if (!api) return;
    let cancelled = false;
    void api.status().then((result) => {
      if (!cancelled && result.ok) setStatus(result.value);
    });
    const unsubscribeStatus = api.onStatusChanged((next) => setStatus(next));
    // Follow live server-state pushes: a backgrounded add resolving to
    // connected/error, or a remove, arrives here without a manual refetch.
    const unsubscribeServers = api.onServersChanged((next) => setServers(next));
    return () => {
      cancelled = true;
      unsubscribeStatus();
      unsubscribeServers();
    };
  }, [api]);

  // Servers only exist once paired; refresh when pairing flips on, clear off.
  useEffect(() => {
    if (status.paired) void loadServers();
    else setServers([]);
  }, [status.paired, loadServers]);

  const runAction = useCallback(
    async (action: BridgeAction, fn: () => Promise<void>): Promise<boolean> => {
      if (!api) return false;
      setBusy(action);
      try {
        await fn();
        return true;
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "Bridge action failed",
        );
        return false;
      } finally {
        setBusy(null);
      }
    },
    [api],
  );

  const pair = useCallback(
    () =>
      runAction("pair", async () => {
        if (!api) return;
        const paired = unwrap(await api.pair());
        // A freshly paired device isn't serving yet — bring the tunnel up so
        // "Enable on this Mac" is one action, not two.
        setStatus(paired.running ? paired : unwrap(await api.start()));
        toast.success("This Mac is now connected to GAIA");
      }),
    [api, runAction],
  );

  const setRunning = useCallback(
    (running: boolean) =>
      runAction("toggle", async () => {
        if (!api) return;
        setStatus(unwrap(await (running ? api.start() : api.stop())));
      }),
    [api, runAction],
  );

  const addServer = useCallback(
    (opts: AddOptions) =>
      runAction("server", async () => {
        if (!api) return;
        setServers(unwrap(await api.addServer(opts)));
        toast.success(`Added ${opts.name ?? "server"}`);
      }),
    [api, runAction],
  );

  const retryServer = useCallback(
    (key: string) =>
      runAction("server", async () => {
        if (!api) return;
        setServers(unwrap(await api.retryServer(key)));
      }),
    [api, runAction],
  );

  const removeServer = useCallback(
    (key: string) =>
      runAction("server", async () => {
        if (!api) return;
        setServers(unwrap(await api.removeServer(key)));
      }),
    [api, runAction],
  );

  return {
    available: api !== null,
    status,
    servers,
    busy,
    pair,
    setRunning,
    addServer,
    retryServer,
    removeServer,
  };
}

/** The shape returned by {@link useBridge}, so the coordinator can own one
 * instance and pass it to the card as a prop (single source of truth). */
export type UseBridge = ReturnType<typeof useBridge>;
