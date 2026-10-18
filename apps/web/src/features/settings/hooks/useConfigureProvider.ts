"use client";

import { useCallback, useState } from "react";
import {
  type ProviderConfigBody,
  providersApi,
  type StoredProviderConfig,
} from "@/features/settings/api/providersApi";
import type {
  CatalogProviderRow,
  CustomPresetId,
} from "@/features/settings/components/providers/providerRows";
import { useProviderConnect } from "@/features/settings/hooks/useProviderConnect";
import type { CustomPreset } from "@/features/settings/utils/customPresets";
import { useConfirmation } from "@/hooks/useConfirmation";
import { toast } from "@/lib/toast";

interface UseConfigureProviderArgs {
  row: CatalogProviderRow;
  presets: readonly CustomPreset[];
  stored?: StoredProviderConfig;
  onSaved: () => void;
}

/**
 * Draft state and actions for one provider's credential form, connected
 * through the shared flow. Seeded once from what is stored; the caller
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
  const [apiSecret, setApiSecret] = useState("");
  // The account half is not secret, so it seeds from what is stored.
  const [accountId, setAccountId] = useState(() => stored?.account_id ?? "");
  const [baseUrl, setBaseUrl] = useState(
    () => stored?.base_url || row.base_url,
  );
  const [model, setModel] = useState(() =>
    row.showModelField ? stored?.model || "" : "",
  );
  const [preset, setPreset] = useState<CustomPresetId>(
    () => presets.find((p) => p.base_url === stored?.base_url)?.key ?? "manual",
  );
  const handleSaved = useCallback(() => {
    toast.success(`${row.label} connected`);
    onSaved();
  }, [row.label, onSaved]);
  const connection = useProviderConnect(row.key, {
    connectionTestable: row.connectionTestable,
    onSaved: handleSaved,
  });

  // Any edit invalidates a previous result.
  const editField = (setter: (value: string) => void) => (value: string) => {
    setter(value);
    connection.reset();
  };

  const selectPreset = (id: CustomPresetId) => {
    setPreset(id);
    connection.reset();
    if (id === "manual") return;
    const match = presets.find((p) => p.key === id);
    if (!match) return;
    setBaseUrl(match.base_url);
    setModel(match.default_model);
  };

  const buildBody = (): ProviderConfigBody => {
    const body: ProviderConfigBody = {};
    if (apiKey.trim()) body.api_key = apiKey.trim();
    if (row.second_key_label && apiSecret.trim()) {
      body.api_secret = apiSecret.trim();
    }
    if (row.account_id_label && accountId.trim()) {
      body.account_id = accountId.trim();
    }
    if (preset !== "manual") body.preset = preset;
    if (baseUrl.trim()) body.base_url = baseUrl.trim();
    if (row.showModelField && model.trim()) body.model = model.trim();
    return body;
  };

  const save = async () => {
    // A stored secret never lingers in its field; the masked hint stands in for it.
    if (await connection.connect(buildBody())) {
      setApiKey("");
      setApiSecret("");
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

  const test = () => connection.test(buildBody());

  return {
    apiKey,
    setApiKey: editField(setApiKey),
    apiSecret,
    setApiSecret: editField(setApiSecret),
    accountId,
    setAccountId: editField(setAccountId),
    baseUrl,
    setBaseUrl: editField(setBaseUrl),
    model,
    setModel: editField(setModel),
    preset,
    selectPreset,
    isSaving: connection.phase === "saving",
    isTesting: connection.phase === "testing",
    testResult: connection.outcome,
    error: connection.error,
    save,
    remove,
    test,
    confirmationProps,
  };
}
