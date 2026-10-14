"use client";

import { useState } from "react";
import {
  extractProviderError,
  getProviderErrorHint,
  type ProviderConfigBody,
  type ProviderTestResult,
  providersApi,
  type StoredProviderConfig,
} from "@/features/settings/api/providersApi";
import type {
  CatalogProviderRow,
  CustomPresetId,
} from "@/features/settings/components/providers/providerRows";
import type { CustomPreset } from "@/features/setup-wizard/utils/providerCards";
import { useConfirmation } from "@/hooks/useConfirmation";
import { toast } from "@/lib/toast";

interface UseConfigureProviderArgs {
  row: CatalogProviderRow;
  presets: readonly CustomPreset[];
  stored?: StoredProviderConfig;
  onSaved: () => void;
}

/**
 * Draft state and actions for one provider's configure dialog. Seeded once
 * from what is stored, since upsert replaces the whole config; the caller
 * remounts per provider. The catalog model stays a placeholder: storing it
 * would pin it past a default change.
 */
export function useConfigureProvider({
  row,
  presets,
  stored,
  onSaved,
}: UseConfigureProviderArgs) {
  const { confirm, confirmationProps } = useConfirmation();
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(
    () => stored?.base_url || row.defaultBaseUrl,
  );
  const [model, setModel] = useState(() =>
    row.showModelField ? stored?.model || "" : "",
  );
  const [preset, setPreset] = useState<CustomPresetId>(
    () => presets.find((p) => p.base_url === stored?.base_url)?.key ?? "manual",
  );
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);

  // Any edit invalidates a previous test: Save unlocks only for what was tested.
  const editField = (setter: (value: string) => void) => (value: string) => {
    setter(value);
    setTestResult(null);
  };

  const selectPreset = (id: CustomPresetId) => {
    setPreset(id);
    setTestResult(null);
    if (id === "manual") return;
    const match = presets.find((p) => p.key === id);
    if (!match) return;
    setBaseUrl(match.base_url);
    setModel(match.default_model);
  };

  const buildBody = (): ProviderConfigBody => {
    const body: ProviderConfigBody = {};
    if (apiKey.trim()) body.api_key = apiKey.trim();
    if (preset !== "manual") body.preset = preset;
    if (baseUrl.trim()) body.base_url = baseUrl.trim();
    if (row.showModelField && model.trim()) body.model = model.trim();
    return body;
  };

  const save = async () => {
    setIsSaving(true);
    try {
      await providersApi.upsertProvider(row.key, buildBody());
      toast.success(`${row.label} connected`);
      onSaved();
    } catch (err: unknown) {
      const detail = extractProviderError(err);
      const hint = detail ? getProviderErrorHint(detail, row.key) : null;
      const message = hint
        ? `${detail} — ${hint}`
        : (detail ?? `Failed to save ${row.label}`);
      toast.error(message);
    } finally {
      setIsSaving(false);
    }
  };

  const remove = async () => {
    const confirmed = await confirm({
      title: `Remove ${row.label}?`,
      message:
        "GAIA will stop using this key. If the same credential is also in your server config, that one still applies.",
      confirmText: "Remove",
      variant: "destructive",
    });
    if (!confirmed) return;
    try {
      await providersApi.deleteProvider(row.key);
      toast.success(`${row.label} removed`);
      onSaved();
    } catch {
      toast.error(`Failed to remove ${row.label}`);
    }
  };

  const test = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      setTestResult(await providersApi.testProvider(row.key, buildBody()));
    } catch (err: unknown) {
      const detail =
        extractProviderError(err) ?? "Could not reach GAIA to run the test.";
      setTestResult({ ok: false, detail, models: [] });
    } finally {
      setIsTesting(false);
    }
  };

  return {
    apiKey,
    setApiKey: editField(setApiKey),
    baseUrl,
    setBaseUrl: editField(setBaseUrl),
    model,
    setModel: editField(setModel),
    preset,
    selectPreset,
    isSaving,
    isTesting,
    testResult,
    save,
    remove,
    test,
    confirmationProps,
  };
}
