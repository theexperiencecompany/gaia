"use client";

import { useCallback, useState } from "react";

interface BearerConnectResult {
  status: string;
  name?: string;
  message?: string;
}

interface UseBearerTokenModalOptions {
  /**
   * Performs the bearer connection for the given integration. Sites differ in
   * which endpoint they hit (native `connect` vs community `add`).
   */
  connect: (
    integrationId: string,
    token: string,
  ) => Promise<BearerConnectResult>;
  /**
   * Runs once the connection succeeds — site-specific success handling such as
   * a toast, cache invalidation, or navigation.
   */
  onConnected: (integrationId: string, result: BearerConnectResult) => void;
}

/**
 * Single source of truth for the bearer-token connect modal. Owns the
 * open/close state (which integration the modal is for) and a `submit` handler
 * shaped for `BearerTokenModal.onSubmit`: it runs the supplied `connect`, calls
 * `onConnected` on success, and throws otherwise so the modal surfaces the
 * error inline and stays open.
 */
export function useBearerTokenModal({
  connect,
  onConnected,
}: UseBearerTokenModalOptions) {
  const [isOpen, setIsOpen] = useState(false);
  const [integrationId, setIntegrationId] = useState("");
  const [integrationName, setIntegrationName] = useState("");

  const open = useCallback((id: string, name: string) => {
    setIntegrationId(id);
    setIntegrationName(name);
    setIsOpen(true);
  }, []);

  const close = useCallback(() => setIsOpen(false), []);

  const submit = useCallback(
    async (id: string, token: string) => {
      const result = await connect(id, token);
      if (result.status === "connected") {
        onConnected(id, result);
        return;
      }
      throw new Error(result.message || `Connection failed: ${result.status}`);
    },
    [connect, onConnected],
  );

  return { isOpen, integrationId, integrationName, open, close, submit };
}
