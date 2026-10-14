"use client";

import { useCallback, useMemo, useState } from "react";
import {
  getProviderErrorHint,
  type ProviderConfigBody,
} from "@/features/settings/api/providersApi";
import { useProviderConnect } from "@/features/settings/hooks/useProviderConnect";
import type { CustomPreset, ProviderCard } from "../utils/providerCards";

/**
 * Draft credentials for one wizard provider card, connected through the shared
 * flow. The base URL starts at the catalog default; the model stays empty (the
 * backend runs its catalog default) unless the user types one or picks a preset.
 */
export function useProviderSetup(config: ProviderCard, onSaved: () => void) {
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(config.base_url);
  const [model, setModel] = useState("");
  const [preset, setPreset] = useState<CustomPreset | null>(null);
  const { isBusy, outcome, error, reset, connect } = useProviderConnect(
    config.key,
    { connectionTestable: config.connectionTestable, onSaved },
  );

  // A new attempt invalidates whatever the previous attempt reported.
  const edit = useCallback(
    (setter: (value: string) => void) => (value: string) => {
      setter(value);
      reset();
    },
    [reset],
  );

  const applyPreset = useCallback(
    (selected: CustomPreset | null) => {
      setPreset(selected);
      setBaseUrl(selected ? selected.base_url : config.base_url);
      setModel(selected ? selected.default_model : "");
      reset();
    },
    [config.base_url, reset],
  );

  const body = useMemo((): ProviderConfigBody => {
    const result: ProviderConfigBody = {};
    if (apiKey.trim()) result.api_key = apiKey.trim();
    if (baseUrl.trim()) result.base_url = baseUrl.trim();
    if (model.trim()) result.model = model.trim();
    if (preset) result.preset = preset.key;
    return result;
  }, [apiKey, baseUrl, model, preset]);

  const save = useCallback(async () => {
    // A stored key never lingers in the card; the server holds it from here on.
    if (await connect(body)) setApiKey("");
  }, [connect, body]);

  const failure = error ?? (outcome && !outcome.ok ? outcome.detail : null);
  const hint = failure ? getProviderErrorHint(failure, config.key_url) : null;

  return {
    apiKey,
    setApiKey: edit(setApiKey),
    baseUrl,
    setBaseUrl: edit(setBaseUrl),
    model,
    setModel: edit(setModel),
    preset,
    applyPreset,
    isBusy,
    outcome,
    error,
    hint,
    connect: save,
  };
}
