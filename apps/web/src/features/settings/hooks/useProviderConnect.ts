"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import {
  type CredentialProvider,
  extractProviderError,
  type ProviderConfigBody,
  type ProviderTestResult,
  providersApi,
} from "@/features/settings/api/providersApi";
import { setupKeys } from "@/features/settings/api/queryKeys";

export type ProviderConnectPhase = "testing" | "saving";

const SAVE_UNREACHABLE_COPY =
  "Couldn't reach GAIA to save — check your connection and try again. Your key wasn't stored.";
const TEST_UNREACHABLE_COPY = "Could not reach GAIA to run the test.";
const SAVED_OUTCOME: ProviderTestResult = {
  ok: true,
  detail: "Saved",
  models: [],
};

/** The reads a stored or removed credential changes: instance status, the masked listing, Composio's setup. */
const CREDENTIAL_DEPENDENT_KEYS = [
  setupKeys.status,
  setupKeys.providers,
  setupKeys.composio,
] as const;

interface ProviderConnectOptions {
  /** Whether the backend can probe this provider; Tavily cannot. */
  connectionTestable: boolean;
}

/**
 * The one connect flow for a provider credential, shared by the setup wizard,
 * Settings and the Ollama one-click: probe first when the provider can be
 * probed, and store only what answered.
 */
export function useProviderConnect(
  provider: CredentialProvider,
  { connectionTestable }: ProviderConnectOptions,
) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<ProviderConnectPhase | null>(null);
  const [outcome, setOutcome] = useState<ProviderTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = useCallback(() => {
    setOutcome(null);
    setError(null);
  }, []);

  const refreshCredentialReads = useCallback(() => {
    for (const queryKey of CREDENTIAL_DEPENDENT_KEYS) {
      void queryClient.invalidateQueries({ queryKey });
    }
  }, [queryClient]);

  const probe = useCallback(
    async (body: ProviderConfigBody): Promise<boolean> => {
      setPhase("testing");
      const result = await providersApi.testProvider(provider, body);
      setOutcome(result);
      return result.ok;
    },
    [provider],
  );

  /** Resolves true once the credential is stored. */
  const connect = useCallback(
    async (body: ProviderConfigBody): Promise<boolean> => {
      reset();
      try {
        if (connectionTestable && !(await probe(body))) return false;
        setPhase("saving");
        await providersApi.upsertProvider(provider, body);
        if (!connectionTestable) setOutcome(SAVED_OUTCOME);
        refreshCredentialReads();
        return true;
      } catch (err) {
        setError(extractProviderError(err) ?? SAVE_UNREACHABLE_COPY);
        return false;
      } finally {
        setPhase(null);
      }
    },
    [provider, connectionTestable, refreshCredentialReads, probe, reset],
  );

  /** Remove the stored credential; rejects with the API's error. */
  const disconnect = useCallback(async (): Promise<void> => {
    await providersApi.deleteProvider(provider);
    refreshCredentialReads();
  }, [provider, refreshCredentialReads]);

  /** Probe without storing anything. */
  const test = useCallback(
    async (body: ProviderConfigBody): Promise<void> => {
      reset();
      try {
        await probe(body);
      } catch (err) {
        setError(extractProviderError(err) ?? TEST_UNREACHABLE_COPY);
      } finally {
        setPhase(null);
      }
    },
    [probe, reset],
  );

  return {
    phase,
    isBusy: phase !== null,
    outcome,
    error,
    reset,
    connect,
    disconnect,
    test,
  };
}
