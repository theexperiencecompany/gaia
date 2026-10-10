"use client";

import { useCallback, useState } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

type ConnectPhase = "idle" | "connecting" | "connected" | "failed";

/**
 * Drives an integration connect from inside the chat card — no modal, no leaving
 * the conversation. Owns the local phase + the bearer token (React state only,
 * cleared on success, never persisted to chat/tool_data). The live catalog
 * (/integrations/me) remains the source of truth once the phase settles.
 */
export function useInlineIntegrationConnect(integrationId: string) {
  const { connectIntegration } = useIntegrations();
  const [phase, setPhase] = useState<ConnectPhase>("idle");
  const [token, setToken] = useState("");
  const [toolsCount, setToolsCount] = useState<number | undefined>();
  const [error, setError] = useState<string | undefined>();

  const connect = useCallback(
    async (bearerToken?: string) => {
      setPhase("connecting");
      setError(undefined);
      try {
        const result = await connectIntegration(integrationId, bearerToken);
        if (result.status === "connected") {
          setToolsCount(result.toolsCount);
          setToken(""); // drop the secret the moment it's no longer needed
          setPhase("connected");
        } else if (result.status === "redirecting") {
          // OAuth: the browser is navigating away; leave the button spinning.
        } else {
          setPhase("failed");
          setError(`Connection failed: ${result.status}`);
        }
      } catch (e) {
        setPhase("failed");
        setError(e instanceof Error ? e.message : "Connection failed");
      }
    },
    [connectIntegration, integrationId],
  );

  return { phase, token, setToken, toolsCount, error, connect };
}
