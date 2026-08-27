"use client";

import { useCallback, useMemo, useState } from "react";
import {
  CUSTOM_PRESETS,
  type CustomPreset,
  extractProviderError,
  getProviderErrorHint,
  type ProviderConfigBody,
  providersApi,
} from "@/features/settings/api/providersApi";
import type { ProviderCardConfig } from "../constants";

export type ProviderSetupPhase = "saving" | "testing";

export interface ProviderTestOutcome {
  ok: boolean;
  detail: string;
  modelCount: number;
}

/**
 * State + connect flow for one provider card. The credential is TESTED first
 * (caller-supplied values via the test endpoint's body — the supported path
 * before anything is stored) and only persisted once the probe passes; a
 * failed test leaves the store untouched so a wrong key can never poison the
 * instance state. Providers the backend cannot probe (Tavily) skip straight
 * to saving. Field defaults come from the card config (and the selected
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
  const [phase, setPhase] = useState<ProviderSetupPhase | null>(null);
  const [outcome, setOutcome] = useState<ProviderTestOutcome | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isBusy = phase !== null;

  /** A new attempt invalidates whatever the previous attempt reported. */
  const resetResult = useCallback(() => {
    setOutcome(null);
    setError(null);
  }, []);

  const updateApiKey = useCallback(
    (value: string) => {
      setApiKey(value);
      resetResult();
    },
    [resetResult],
  );

  const updateBaseUrl = useCallback(
    (value: string) => {
      setBaseUrl(value);
      resetResult();
    },
    [resetResult],
  );

  const updateModel = useCallback(
    (value: string) => {
      setModel(value);
      resetResult();
    },
    [resetResult],
  );

  const applyPreset = useCallback(
    (selected: CustomPreset | null) => {
      setPreset(selected);
      setBaseUrl(selected ? selected.baseUrl : config.defaultBaseUrl);
      setModel(selected ? selected.defaultModel : config.defaultModel);
      resetResult();
    },
    [config.defaultBaseUrl, config.defaultModel, resetResult],
  );

  const body = useMemo((): ProviderConfigBody => {
    const result: ProviderConfigBody = {};
    if (apiKey.trim()) result.api_key = apiKey.trim();
    if (baseUrl.trim()) result.base_url = baseUrl.trim();
    if (model.trim()) result.model = model.trim();
    if (preset) result.preset = preset.key;
    return result;
  }, [apiKey, baseUrl, model, preset]);

  const connect = useCallback(async () => {
    resetResult();
    try {
      if (config.connectionTestable) {
        setPhase("testing");
        const test = await providersApi.testProvider(config.key, body);
        if (!test.ok) {
          // Red pill with the probe's detail — and nothing persisted.
          setOutcome({
            ok: false,
            detail: test.detail,
            modelCount: test.models?.length ?? 0,
          });
          return;
        }
        setOutcome({
          ok: true,
          detail: test.detail,
          modelCount: test.models?.length ?? 0,
        });
      }
      setPhase("saving");
      await providersApi.upsertProvider(config.key, body);
      if (!config.connectionTestable) {
        setOutcome({ ok: true, detail: "Saved", modelCount: 0 });
      }
      // Clear the pasted key so a re-opened card never shows stale secret
      // material; the stored credential is server-side from here on.
      setApiKey("");
      onSaved();
    } catch (err) {
      setError(
        extractProviderError(err) ?? "Something went wrong while saving.",
      );
    } finally {
      setPhase(null);
    }
  }, [config.key, config.connectionTestable, body, onSaved, resetResult]);

  const errorHint = error ? getProviderErrorHint(error, config.key) : null;
  const outcomeHint =
    outcome && !outcome.ok
      ? getProviderErrorHint(outcome.detail, config.key)
      : null;
  const hint = errorHint ?? outcomeHint;

  return {
    apiKey,
    setApiKey: updateApiKey,
    baseUrl,
    setBaseUrl: updateBaseUrl,
    model,
    setModel: updateModel,
    preset,
    applyPreset,
    presets: CUSTOM_PRESETS,
    isBusy,
    outcome,
    error,
    hint,
    errorHint,
    outcomeHint,
    connect,
  };
}
