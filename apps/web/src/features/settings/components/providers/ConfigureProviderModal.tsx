"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import type { StoredProviderConfig } from "@/features/settings/api/providersApi";
import { useConfigureProvider } from "@/features/settings/hooks/useConfigureProvider";
import type { CustomPreset } from "@/features/setup-wizard/utils/providerCards";
import { ProviderApiKeyInput } from "./ProviderApiKeyInput";
import { ProviderFavicon } from "./ProviderFavicon";
import { ProviderTestResultNotice } from "./ProviderTestResultNotice";
import type { CatalogProviderRow, CustomPresetId } from "./providerRows";

interface ConfigureProviderModalProps {
  row: CatalogProviderRow;
  /** Gateway chips offered when configuring the custom lane. */
  presets: readonly CustomPreset[];
  /** Masked stored config for this row, when the listing has loaded. */
  stored?: StoredProviderConfig;
  isConfigured: boolean;
  onSaved: () => void;
  onClose: () => void;
}

/** Mount one per provider (keyed by row) so its draft seeds from `stored`. */
export function ConfigureProviderModal({
  row,
  presets,
  stored,
  isConfigured,
  onSaved,
  onClose,
}: ConfigureProviderModalProps) {
  const form = useConfigureProvider({ row, presets, stored, onSaved });
  // A stored key can never be read back (only its last four chars are listed).
  // Leaving the field empty keeps it: the backend merges a partial save.
  const storedKeyHint = stored?.api_key_hint;
  const showPresetChips = row.key === "custom";
  const awaitingPassingTest =
    row.connectionTestable && form.testResult?.ok !== true;
  const presetChips: ReadonlyArray<{ id: CustomPresetId; label: string }> = [
    ...presets.map((p) => ({ id: p.key, label: p.label })),
    { id: "manual", label: "Manual" },
  ];

  return (
    <>
      <Modal isOpen onClose={onClose} size="md">
        <ModalContent>
          <ModalHeader className="flex-row items-center gap-3">
            <ProviderFavicon domain={row.faviconDomain} />
            Configure {row.label}
          </ModalHeader>
          <ModalBody className="gap-4">
            <ProviderApiKeyInput
              provider={row.key}
              autoFocus
              placeholder={
                storedKeyHint
                  ? `Stored (${storedKeyHint}) — paste to replace`
                  : `Paste your ${row.label} key`
              }
              description={
                storedKeyHint
                  ? "Saved — leave empty to keep it, or paste to replace."
                  : undefined
              }
              value={form.apiKey}
              onValueChange={form.setApiKey}
            />
            {showPresetChips && (
              <div className="space-y-2">
                <p className="text-xs font-medium tracking-wider text-zinc-500 uppercase">
                  Preset gateway
                </p>
                <div className="flex gap-2">
                  {presetChips.map((chip) => (
                    <Button
                      key={chip.id}
                      size="sm"
                      variant={form.preset === chip.id ? "flat" : "light"}
                      color={form.preset === chip.id ? "primary" : "default"}
                      onPress={() => form.selectPreset(chip.id)}
                    >
                      {chip.label}
                    </Button>
                  ))}
                </div>
              </div>
            )}
            {(row.needsBaseUrl || showPresetChips) && (
              <Input
                label="Base URL"
                placeholder={
                  row.defaultBaseUrl || "https://your-gateway.example.com/v1"
                }
                value={form.baseUrl}
                onValueChange={form.setBaseUrl}
              />
            )}
            {row.showModelField && (
              <Input
                label="Model"
                placeholder={row.defaultModel || "Default"}
                description="Leave empty to use the endpoint default."
                value={form.model}
                onValueChange={form.setModel}
              />
            )}
            {form.testResult && (
              <ProviderTestResultNotice
                result={form.testResult}
                provider={row.key}
              />
            )}
            {awaitingPassingTest && (
              <p className="text-xs text-zinc-500">
                Run Test first — Save unlocks after a passing test.
              </p>
            )}
          </ModalBody>
          <ModalFooter>
            {isConfigured && (
              <Button
                color="danger"
                variant="light"
                size="sm"
                onPress={() => {
                  void form.remove();
                }}
              >
                Remove
              </Button>
            )}
            <Button variant="flat" size="sm" onPress={onClose}>
              Cancel
            </Button>
            {row.connectionTestable && (
              <Button
                variant="flat"
                color="default"
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
              size="sm"
              isLoading={form.isSaving}
              isDisabled={form.isTesting || awaitingPassingTest}
              onPress={() => {
                void form.save();
              }}
            >
              Save
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
      <ConfirmationDialog {...form.confirmationProps} />
    </>
  );
}
