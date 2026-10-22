"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
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

  const showPresetChips = row.key === "custom";
  const isBusy = form.isSaving || form.isTesting;

  return (
    <div className="flex flex-col gap-3">
      {row.account_id_label && (
        <Input
          label={row.account_id_label}
          value={form.accountId}
          onValueChange={form.setAccountId}
          autoComplete="off"
          isDisabled={isBusy}
        />
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
        <Input
          label="Base URL"
          placeholder={row.base_url ?? "https://your-gateway.example.com/v1"}
          value={form.baseUrl}
          onValueChange={form.setBaseUrl}
          isDisabled={isBusy}
        />
      )}
      {row.takes_model && (
        <Input
          label="Model"
          placeholder={row.default_model ?? "Default"}
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
        <Button
          key={chip.id}
          size="sm"
          radius="full"
          variant={selected === chip.id ? "flat" : "light"}
          color={selected === chip.id ? "primary" : "default"}
          onPress={() => onSelect(chip.id)}
        >
          {chip.label}
        </Button>
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
          color="danger"
          variant="light"
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
        <Button
          variant="flat"
          size="sm"
          isLoading={isTesting}
          isDisabled={isSaving}
          onPress={() => {
            void onTest();
          }}
        >
          Test
        </Button>
      )}
      <Button
        color="primary"
        variant="flat"
        size="sm"
        isLoading={isSaving}
        isDisabled={isTesting}
        onPress={() => {
          void onSave();
        }}
      >
        {testable ? "Test & Save" : "Save"}
      </Button>
    </div>
  );
}
