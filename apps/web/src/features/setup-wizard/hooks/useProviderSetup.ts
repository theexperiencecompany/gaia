"use client";

import { useCallback, useMemo, useState } from "react";
import {
  type ProviderConfigBody,
  providersApi,
} from "@/features/settings/api/providersApi";
import {
  CUSTOM_PRESETS,
  type CustomPreset,
  type ProviderCardConfig,
} from "../constants";

export type ProviderSetupPhase = "idle" | "saving" | "testing";

export interface ProviderTestOutcome {
  ok: boolean;
  detail: string;
  modelCount: number;
}

/**
 * State + save/test flow for one provider card. "Test & Save" persists the
 * credential (PUT) then probes it (POST test); the outcome renders inline in
 * the card. Field defaults come from the card config (and the selected
 * preset, for the Custom card).
 */
export function useProviderSetup(
  config: ProviderCardConfig,
  onSaved: () => void,
) {
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(config.defaultBaseUrl);
  const [model, setModel] = useState(config.defaultModel);
  const [preset, setPreset] = useState<CustomPreset | null>(null);
  const [phase, setPhase] = useState<ProviderSetupPhase>("idle");
  const [outcome, setOutcome] = useState<ProviderTestOutcome | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isBusy = phase === "saving" || phase === "testing";

  const applyPreset = useCallback(
    (selected: CustomPreset | null) => {
      setPreset(selected);
      setBaseUrl(selected ? selected.baseUrl : config.defaultBaseUrl);
      setModel(selected ? selected.defaultModel : config.defaultModel);
      setOutcome(null);
      setError(null);
    },
    [config.defaultBaseUrl, config.defaultModel],
  );

  const body = useMemo((): ProviderConfigBody => {
    const result: ProviderConfigBody = {};
    if (apiKey.trim()) result.api_key = apiKey.trim();
    if (baseUrl.trim()) result.base_url = baseUrl.trim();
    if (model.trim()) result.model = model.trim();
    if (preset) result.preset = preset.key;
    return result;
  }, [apiKey, baseUrl, model, preset]);

  const testAndSave = useCallback(async () => {
    setPhase("saving");
    setError(null);
    setOutcome(null);
    try {
      await providersApi.upsertProvider(config.key, body);
      setPhase("testing");
      const test = await providersApi.testProvider(config.key);
      setOutcome({
        ok: test.ok,
        detail: test.detail,
        modelCount: test.models?.length ?? 0,
      });
      if (test.ok) {
        // Clear the pasted key so a re-opened card never shows stale secret
        // material; the stored credential is server-side from here on.
        setApiKey("");
        onSaved();
      }
    } catch (err) {
      setError(extractProviderError(err));
    } finally {
      setPhase("idle");
    }
  }, [config.key, body, onSaved]);

  return {
    apiKey,
    setApiKey,
    baseUrl,
    setBaseUrl,
    model,
    setModel,
    preset,
    applyPreset,
    presets: CUSTOM_PRESETS,
    isBusy,
    outcome,
    error,
    testAndSave,
  };
}

/** Pull a human-readable message out of an axios/backend error. */
function extractProviderError(err: unknown): string {
  if (typeof err === "object" && err !== null) {
    const data = (err as { response?: { data?: unknown } }).response?.data;
    if (typeof data === "object" && data !== null) {
      const record = data as Record<string, unknown>;
      if (typeof record.detail === "string") return record.detail;
      if (
        typeof record.detail === "object" &&
        record.detail !== null &&
        typeof (record.detail as Record<string, unknown>).message === "string"
      ) {
        return (record.detail as Record<string, unknown>).message as string;
      }
    }
    if (err instanceof Error && err.message) return err.message;
  }
  return "Something went wrong while saving.";
}
