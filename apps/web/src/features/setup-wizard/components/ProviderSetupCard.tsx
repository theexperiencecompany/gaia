/**
 * One provider card inside the setup wizard: brand favicon, credential
 * inputs (per provider shape), preset chips for OpenAI-compatible endpoints,
 * and the shared connect flow (probe, then store), rendering the result
 * (Connected · N models, Saved, or the failure detail) in place. Providers
 * the backend cannot probe (Tavily) save directly.
 */

"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { KeyIcon, McpServerIcon } from "@icons";
import Image from "next/image";
import { providerFaviconUrl } from "@/features/settings/api/providersApi";
import { ProviderApiKeyInput } from "@/features/settings/components/providers/ProviderApiKeyInput";
import { useProviderSetup } from "../hooks/useProviderSetup";
import type { CustomPreset, ProviderCard } from "../utils/providerCards";
import { OllamaOneClick } from "./OllamaOneClick";
import { ProviderOutcomeLine } from "./ProviderOutcomeLine";

interface ProviderSetupCardProps {
  config: ProviderCard;
  /** Whether this provider already has a stored credential. */
  isConfigured: boolean;
  /** Fired after a successful save so parents can refresh setup status. */
  onSaved: () => void;
}

export function ProviderSetupCard({
  config,
  isConfigured,
  onSaved,
}: ProviderSetupCardProps) {
  const {
    apiKey,
    setApiKey,
    baseUrl,
    setBaseUrl,
    model,
    setModel,
    preset,
    applyPreset,
    isBusy,
    outcome,
    error,
    hint,
    connect,
  } = useProviderSetup(config, onSaved);

  const canSave =
    (!config.showApiKey || apiKey.trim().length > 0) &&
    (!config.needs_base_url || baseUrl.trim().length > 0);

  return (
    <div className="w-full rounded-2xl bg-zinc-900 p-4">
      <div className="mb-1 flex items-center gap-3">
        <ProviderCardIcon config={config} preset={preset} />
        <p className="flex-1 text-sm font-medium text-zinc-100">
          {config.label}
        </p>
        {isConfigured && (
          <span className="rounded-full bg-emerald-400/10 px-2 py-0.5 text-xs text-emerald-400">
            Connected
          </span>
        )}
      </div>
      <p className="mb-3 text-xs text-zinc-500">{config.description}</p>

      {config.key === "ollama" && (
        <OllamaOneClick config={config} parentBusy={isBusy} onSaved={onSaved} />
      )}

      {config.hasPresets && (
        <PresetChips
          presets={config.presets}
          selected={preset}
          onSelect={applyPreset}
        />
      )}

      <div className="space-y-2">
        {config.showApiKey && (
          <ProviderApiKeyInput
            keyUrl={config.key_url}
            placeholder="Paste your API key"
            value={apiKey}
            onValueChange={setApiKey}
            autoComplete="off"
            startContent={<KeyIcon size={16} className="text-zinc-500" />}
            size="sm"
            radius="md"
            variant="faded"
            isDisabled={isBusy}
          />
        )}
        {config.needs_base_url && (
          <Input
            label="Base URL"
            placeholder={
              config.base_url || "https://your-gateway.example.com/v1"
            }
            value={baseUrl}
            onValueChange={setBaseUrl}
            size="sm"
            radius="md"
            variant="faded"
            isDisabled={isBusy}
          />
        )}
        {config.showModel && (
          <Input
            label="Model"
            placeholder={config.default_model || "Default"}
            description="Leave empty to use the endpoint default."
            value={model}
            onValueChange={setModel}
            size="sm"
            radius="md"
            variant="faded"
            isDisabled={isBusy}
          />
        )}
      </div>

      <div className="mt-3 flex items-center justify-between gap-2">
        <ProviderOutcomeLine
          outcome={outcome}
          error={error}
          hint={hint}
          savedLabel={config.connectionTestable ? "Connected" : "Saved"}
          showModelCount={config.connectionTestable}
        />
        <Button
          size="sm"
          color="primary"
          variant="flat"
          isLoading={isBusy}
          isDisabled={!canSave || isBusy}
          onPress={connect}
        >
          {config.connectionTestable ? "Test & Save" : "Save"}
        </Button>
      </div>
    </div>
  );
}

function ProviderCardIcon({
  config,
  preset,
}: {
  config: ProviderCard;
  preset: CustomPreset | null;
}) {
  // A preset-driven card shows a neutral glyph until a gateway is picked.
  if (config.hasPresets && !preset) {
    return (
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-zinc-800">
        <McpServerIcon size={16} className="text-zinc-300" />
      </span>
    );
  }
  return (
    <Image
      src={providerFaviconUrl(preset?.favicon_domain ?? config.favicon_domain)}
      alt={`${config.label} icon`}
      width={24}
      height={24}
      className="shrink-0 rounded-md"
    />
  );
}

function PresetChips({
  presets,
  selected,
  onSelect,
}: {
  presets: readonly CustomPreset[];
  selected: CustomPreset | null;
  onSelect: (preset: CustomPreset | null) => void;
}) {
  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {presets.map((p) => (
        <Button
          key={p.key}
          size="sm"
          radius="full"
          variant="flat"
          color={selected?.key === p.key ? "primary" : "default"}
          onPress={() => onSelect(selected?.key === p.key ? null : p)}
        >
          {p.label}
        </Button>
      ))}
    </div>
  );
}
