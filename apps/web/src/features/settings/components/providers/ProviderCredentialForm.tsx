"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import type { StoredProviderConfig } from "@/features/settings/api/providersApi";
import { useConfigureProvider } from "@/features/settings/hooks/useConfigureProvider";
import type { CustomPreset } from "@/features/setup-wizard/utils/providerCards";
import { ProviderApiKeyInput } from "./ProviderApiKeyInput";
import { ProviderTestResultNotice } from "./ProviderTestResultNotice";
import type { CatalogProviderRow, CustomPresetId } from "./providerRows";

interface ProviderCredentialFormProps {
  row: CatalogProviderRow;
  /** Gateway chips offered when configuring the custom lane. */
  presets: readonly CustomPreset[];
  /** Masked stored config for this row, when the listing has loaded. */
  stored?: StoredProviderConfig;
  isConfigured: boolean;
  /** The saved key overrides a different one set in the environment. */
  overridesEnv: boolean;
  onSaved: () => void;
}

/** One provider's credential fields and actions; mount one per provider (keyed by row) so its draft seeds from `stored`. */
export function ProviderCredentialForm({
  row,
  presets,
  stored,
  isConfigured,
  overridesEnv,
  onSaved,
}: ProviderCredentialFormProps) {
  const form = useConfigureProvider({ row, presets, stored, onSaved });

  // A stored key can never be read back (only its last four chars are listed).
  // Leaving the field empty keeps it: the backend merges a partial save.
  const storedKeyHint = stored?.api_key_hint;
  const showPresetChips = row.key === "custom";
  const presetChips: ReadonlyArray<{ id: CustomPresetId; label: string }> = [
    ...presets.map((p) => ({ id: p.key, label: p.label })),
    { id: "manual", label: "Manual" },
  ];
  const isBusy = form.isSaving || form.isTesting;

  return (
    <div className="flex flex-col gap-3">
      {row.showApiKey && (
        <ProviderApiKeyInput
          keyUrl={row.key_url}
          placeholder={
            storedKeyHint
              ? `Stored (${storedKeyHint}), paste to replace`
              : `Paste your ${row.label} key`
          }
          description={
            storedKeyHint
              ? "Saved. Leave empty to keep it, or paste to replace."
              : undefined
          }
          value={form.apiKey}
          onValueChange={form.setApiKey}
          autoComplete="off"
          isDisabled={isBusy}
        />
      )}
      {showPresetChips && (
        <div className="flex flex-wrap gap-2">
          {presetChips.map((chip) => (
            <Button
              key={chip.id}
              size="sm"
              radius="full"
              variant={form.preset === chip.id ? "flat" : "light"}
              color={form.preset === chip.id ? "primary" : "default"}
              onPress={() => form.selectPreset(chip.id)}
            >
              {chip.label}
            </Button>
          ))}
        </div>
      )}
      {(row.needs_base_url || showPresetChips) && (
        <Input
          label="Base URL"
          placeholder={row.base_url || "https://your-gateway.example.com/v1"}
          value={form.baseUrl}
          onValueChange={form.setBaseUrl}
          isDisabled={isBusy}
        />
      )}
      {row.showModelField && (
        <Input
          label="Model"
          placeholder={row.default_model || "Default"}
          description="Leave empty to use the endpoint default."
          value={form.model}
          onValueChange={form.setModel}
          isDisabled={isBusy}
        />
      )}
      {overridesEnv && (
        <p className="text-xs text-zinc-500">
          Your saved key overrides a different one set in the environment.
        </p>
      )}
      {form.testResult && (
        <ProviderTestResultNotice
          result={form.testResult}
          keyUrl={row.key_url}
        />
      )}
      {form.error && (
        <ProviderTestResultNotice
          result={{ ok: false, detail: form.error, models: [] }}
          keyUrl={row.key_url}
        />
      )}
      <div className="flex items-center justify-end gap-2">
        {isConfigured && (
          <Button
            color="danger"
            variant="light"
            size="sm"
            className="mr-auto"
            isDisabled={isBusy}
            onPress={() => {
              void form.remove();
            }}
          >
            Remove
          </Button>
        )}
        {row.connectionTestable && (
          <Button
            variant="flat"
            size="sm"
            isLoading={form.isTesting}
            isDisabled={form.isSaving}
            onPress={() => {
              void form.test();
            }}
          >
            Test
          </Button>
        )}
        <Button
          color="primary"
          variant="flat"
          size="sm"
          isLoading={form.isSaving}
          isDisabled={form.isTesting}
          onPress={() => {
            void form.save();
          }}
        >
          {row.connectionTestable ? "Test & Save" : "Save"}
        </Button>
      </div>
      <ConfirmationDialog {...form.confirmationProps} />
    </div>
  );
}
