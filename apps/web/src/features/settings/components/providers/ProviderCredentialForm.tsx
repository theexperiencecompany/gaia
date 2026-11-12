"use client";

import { Button, Description, Input, Label, TextField } from "@heroui/react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { GaiaButton } from "@/components/shared/GaiaButton";
import type { StoredProviderConfig } from "@/features/settings/api/providersApi";
import { useConfigureProvider } from "@/features/settings/hooks/useConfigureProvider";
import type { CustomPreset } from "@/features/settings/utils/customPresets";
import type { CatalogProvider } from "@/features/settings/utils/providerCatalog";
import { ProviderApiKeyInput } from "./ProviderApiKeyInput";
import { ProviderTestResultNotice } from "./ProviderTestResultNotice";
import type { CustomPresetId } from "./providerRows";

interface ProviderCredentialFormProps {
  row: CatalogProvider;
  /** Gateway chips offered when configuring the custom lane. */
  presets: readonly CustomPreset[];
  /** Masked stored config for this row, when the listing has loaded. */
  stored?: StoredProviderConfig;
  isConfigured: boolean;
  /** The saved key overrides a different one set in the environment. */
  overridesEnv: boolean;
}

/** One provider's credential fields and actions; mount one per provider (keyed by row) so its draft seeds from `stored`. */
export function ProviderCredentialForm({
  row,
  presets,
  stored,
  isConfigured,
  overridesEnv,
}: ProviderCredentialFormProps) {
  const form = useConfigureProvider({ row, presets, stored });

  const showPresetChips = row.key === "custom";
  const isBusy = form.isSaving || form.isTesting;

  return (
    <div className="flex flex-col gap-3">
      {row.account_id_label && (
        <TextField
          value={form.accountId}
          onChange={form.setAccountId}
          isDisabled={isBusy}
        >
          <Label>{row.account_id_label}</Label>
          <Input autoComplete="off" />
        </TextField>
      )}
      {row.takes_key && (
        <ProviderApiKeyInput
          label={row.api_key_label}
          keyUrl={row.key_url}
          {...storedSecretHints(
            stored?.api_key_hint,
            `Paste your ${row.label} key`,
          )}
          value={form.apiKey}
          onValueChange={form.setApiKey}
          autoComplete="off"
          isDisabled={isBusy}
        />
      )}
      {row.second_key_label && (
        <ProviderApiKeyInput
          label={row.second_key_label}
          keyUrl={null}
          {...storedSecretHints(
            stored?.api_secret_hint,
            `Paste your ${row.second_key_label}`,
          )}
          value={form.apiSecret}
          onValueChange={form.setApiSecret}
          autoComplete="off"
          isDisabled={isBusy}
        />
      )}
      {showPresetChips && (
        <PresetChips
          presets={presets}
          selected={form.preset}
          onSelect={form.selectPreset}
        />
      )}
      {(row.needs_base_url || showPresetChips) && (
        <TextField
          value={form.baseUrl}
          onChange={form.setBaseUrl}
          isDisabled={isBusy}
        >
          <Label>Base URL</Label>
          <Input
            placeholder={row.base_url ?? "https://your-gateway.example.com/v1"}
          />
        </TextField>
      )}
      {row.takes_model && (
        <TextField
          value={form.model}
          onChange={form.setModel}
          isDisabled={isBusy}
        >
          <Label>Model</Label>
          <Input placeholder={row.default_model ?? "Default"} />
          <Description>Leave empty to use the endpoint default.</Description>
        </TextField>
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
          result={{ ok: false, detail: form.error, failure: null, models: [] }}
          keyUrl={row.key_url}
        />
      )}
      <ProviderFormActions
        canRemove={isConfigured}
        testable={row.connectionTestable}
        isSaving={form.isSaving}
        isTesting={form.isTesting}
        onRemove={form.remove}
        onTest={form.test}
        onSave={form.save}
      />
      <ConfirmationDialog {...form.confirmationProps} />
    </div>
  );
}

/** A stored secret is never read back, only its last four chars; an empty field keeps it since the backend merges partial saves. */
function storedSecretHints(
  hint: string | null | undefined,
  emptyPlaceholder: string,
): { placeholder: string; description?: string } {
  if (!hint) return { placeholder: emptyPlaceholder };
  return {
    placeholder: `Stored (${hint}), paste to replace`,
    description: "Saved. Leave empty to keep it, or paste to replace.",
  };
}

interface PresetChipsProps {
  presets: readonly CustomPreset[];
  selected: CustomPresetId;
  onSelect: (id: CustomPresetId) => void;
}

function PresetChips({ presets, selected, onSelect }: PresetChipsProps) {
  const chips: ReadonlyArray<{ id: CustomPresetId; label: string }> = [
    ...presets.map((p) => ({ id: p.key, label: p.label })),
    { id: "manual", label: "Manual" },
  ];
  return (
    <div className="flex flex-wrap gap-2">
      {chips.map((chip) => (
        <GaiaButton
          shape="pill"
          key={chip.id}
          size="sm"
          className=""
          variant={selected === chip.id ? "secondary" : "ghost"}
          onPress={() => onSelect(chip.id)}
        >
          {chip.label}
        </GaiaButton>
      ))}
    </div>
  );
}

interface ProviderFormActionsProps {
  canRemove: boolean;
  testable: boolean;
  isSaving: boolean;
  isTesting: boolean;
  onRemove: () => Promise<void>;
  onTest: () => Promise<unknown>;
  onSave: () => Promise<void>;
}

function ProviderFormActions({
  canRemove,
  testable,
  isSaving,
  isTesting,
  onRemove,
  onTest,
  onSave,
}: ProviderFormActionsProps) {
  const isBusy = isSaving || isTesting;
  return (
    <div className="flex items-center justify-end gap-2">
      {canRemove && (
        <Button
          variant="danger-soft"
          size="sm"
          className="mr-auto"
          isDisabled={isBusy}
          onPress={() => {
            void onRemove();
          }}
        >
          Remove
        </Button>
      )}
      {testable && (
        <GaiaButton
          variant="default-soft"
          size="sm"
          isPending={isTesting}
          isDisabled={isSaving}
          onPress={() => {
            void onTest();
          }}
        >
          Test
        </GaiaButton>
      )}
      <GaiaButton
        variant="accent-soft"
        size="sm"
        isPending={isSaving}
        isDisabled={isTesting}
        onPress={() => {
          void onSave();
        }}
      >
        {testable ? "Test & Save" : "Save"}
      </GaiaButton>
    </div>
  );
}
