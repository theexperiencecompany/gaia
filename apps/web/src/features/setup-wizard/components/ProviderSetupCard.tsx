/**
 * One provider card inside the setup wizard: brand favicon, credential
 * inputs (per provider shape), preset chips for OpenAI-compatible endpoints,
 * and an inline connect flow that probes then persists the credential,
 * rendering the result (Connected · N models, Saved, or the failure detail)
 * in place. Providers the backend cannot probe (Tavily) save directly.
 */

"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  Alert01Icon,
  KeyIcon,
  McpServerIcon,
  SquareArrowUpRight02Icon,
  Tick02Icon,
  ViewIcon,
  ViewOffSlashIcon,
} from "@icons";
import Image from "next/image";
import { useState } from "react";
import {
  extractProviderError,
  getProviderErrorHint,
  PROVIDER_KEY_URLS,
  providerFaviconUrl,
  providersApi,
} from "@/features/settings/api/providersApi";
import { OLLAMA_ONE_CLICK, type ProviderCardConfig } from "../constants";
import { useProviderSetup } from "../hooks/useProviderSetup";

interface ProviderSetupCardProps {
  config: ProviderCardConfig;
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
  const [isKeyVisible, setIsKeyVisible] = useState(false);
  const {
    apiKey,
    setApiKey,
    baseUrl,
    setBaseUrl,
    model,
    setModel,
    preset,
    applyPreset,
    presets,
    isBusy,
    outcome,
    error,
    hint,
    connect,
  } = useProviderSetup(config, onSaved);

  const canSave =
    (!config.showApiKey || apiKey.trim().length > 0) &&
    (!config.showBaseUrl || baseUrl.trim().length > 0);

  const faviconDomain =
    preset && config.presetFavicon
      ? (config.presetFavicon[preset.key] ?? config.faviconDomain)
      : config.faviconDomain;

  return (
    <div className="w-full rounded-2xl bg-zinc-800 p-4">
      <div className="mb-1 flex items-center gap-3">
        {config.hasPresets && !preset ? (
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-zinc-900">
            <McpServerIcon size={16} className="text-zinc-300" />
          </span>
        ) : (
          <Image
            src={providerFaviconUrl(faviconDomain)}
            alt={`${config.label} icon`}
            width={24}
            height={24}
            className="shrink-0 rounded-md"
          />
        )}
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
        <div className="mb-3 flex flex-wrap gap-2">
          {presets.map((p) => (
            <Button
              key={p.key}
              size="sm"
              radius="full"
              variant="flat"
              color={preset?.key === p.key ? "primary" : "default"}
              onPress={() => applyPreset(preset?.key === p.key ? null : p)}
            >
              {p.label}
            </Button>
          ))}
        </div>
      )}

      <div className="space-y-2">
        {config.showApiKey && (
          <>
            <Input
              type={isKeyVisible ? "text" : "password"}
              placeholder="Paste your API key"
              value={apiKey}
              onValueChange={setApiKey}
              autoComplete="off"
              startContent={<KeyIcon size={16} className="text-zinc-500" />}
              endContent={
                <Button
                  isIconOnly
                  size="sm"
                  variant="light"
                  radius="full"
                  aria-label={isKeyVisible ? "Hide API key" : "Show API key"}
                  onPress={() => setIsKeyVisible((visible) => !visible)}
                  className="text-zinc-500"
                >
                  {isKeyVisible ? (
                    <ViewOffSlashIcon size={16} />
                  ) : (
                    <ViewIcon size={16} />
                  )}
                </Button>
              }
              size="sm"
              radius="md"
              isDisabled={isBusy}
            />
            {PROVIDER_KEY_URLS[config.key] && (
              <a
                href={PROVIDER_KEY_URLS[config.key]}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300"
              >
                Get your key
                <SquareArrowUpRight02Icon size={12} />
              </a>
            )}
          </>
        )}
        {config.showBaseUrl && (
          <Input
            placeholder="Base URL"
            value={baseUrl}
            onValueChange={setBaseUrl}
            size="sm"
            radius="md"
            isDisabled={isBusy}
          />
        )}
        {config.showModel && (
          <Input
            placeholder="Model (e.g. llama3.2)"
            value={model}
            onValueChange={setModel}
            size="sm"
            radius="md"
            isDisabled={isBusy}
          />
        )}
      </div>

      <div className="mt-3 flex items-center justify-between gap-2">
        <OutcomeLine
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

function OllamaOneClick({
  config,
  parentBusy,
  onSaved,
}: {
  config: ProviderCardConfig;
  parentBusy: boolean;
  onSaved: () => void;
}) {
  const [ollamaBusy, setOllamaBusy] = useState(false);
  const [ollamaOutcome, setOllamaOutcome] =
    useState<ReturnType<typeof useProviderSetup>["outcome"]>(null);
  const [ollamaError, setOllamaError] = useState<string | null>(null);

  const handleOllamaOneClick = async () => {
    setOllamaBusy(true);
    setOllamaOutcome(null);
    setOllamaError(null);
    try {
      await providersApi.upsertProvider("ollama", {
        base_url: config.defaultBaseUrl || OLLAMA_ONE_CLICK.baseUrl,
        model: config.defaultModel || OLLAMA_ONE_CLICK.model,
      });
      setOllamaOutcome({ ok: true, detail: "Saved", modelCount: 0 });
      onSaved();
    } catch (err) {
      setOllamaError(
        extractProviderError(err) ?? "Something went wrong while saving.",
      );
    } finally {
      setOllamaBusy(false);
    }
  };

  const hint = (() => {
    if (ollamaError) return getProviderErrorHint(ollamaError, "ollama");
    if (ollamaOutcome && !ollamaOutcome.ok)
      return getProviderErrorHint(ollamaOutcome.detail, "ollama");
    return null;
  })();

  return (
    <div className="mb-3 rounded-xl bg-zinc-900 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-medium text-zinc-100">
            Quick setup — local Ollama
          </p>
          <p className="text-xs text-zinc-500">
            Free, no API key needed. One click to use your local model.
          </p>
        </div>
        <Button
          size="sm"
          color="primary"
          variant="flat"
          isLoading={ollamaBusy}
          isDisabled={ollamaBusy || parentBusy}
          onPress={handleOllamaOneClick}
        >
          Use local Ollama
        </Button>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-zinc-500">
        Requires Ollama running on your host:{" "}
        <code className="rounded bg-zinc-800 px-1 py-0.5 text-xs text-zinc-300">
          ollama pull {OLLAMA_ONE_CLICK.model} && ollama serve
        </code>{" "}
        —{" "}
        <a
          href="https://ollama.com"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-zinc-400 hover:text-zinc-200"
        >
          ollama.com <SquareArrowUpRight02Icon size={10} />
        </a>
      </p>
      {(ollamaOutcome || ollamaError) && (
        <div className="mt-2">
          <OutcomeLine
            outcome={ollamaOutcome}
            error={ollamaError}
            hint={hint}
            savedLabel="Saved"
            showModelCount={false}
          />
        </div>
      )}
    </div>
  );
}

function OutcomeLine({
  outcome,
  error,
  hint,
  savedLabel,
  showModelCount,
}: {
  outcome: ReturnType<typeof useProviderSetup>["outcome"];
  error: string | null;
  hint?: string | null;
  /** Label for a successful outcome — probed providers connect, others save. */
  savedLabel: string;
  showModelCount: boolean;
}) {
  if (error) {
    return (
      <div className="flex min-w-0 flex-col gap-1">
        <span
          title={error}
          className="flex min-w-0 items-center gap-1 rounded-full bg-red-400/10 px-2 py-0.5 text-xs text-red-400"
        >
          <Alert01Icon height={14} className="shrink-0" />
          <span className="truncate">{error}</span>
        </span>
        {hint && (
          <span className="text-xs leading-relaxed text-zinc-500">{hint}</span>
        )}
      </div>
    );
  }
  if (!outcome) return null;
  if (!outcome.ok) {
    const detail = outcome.detail || "Test failed";
    return (
      <div className="flex min-w-0 flex-col gap-1">
        <span
          title={detail}
          className="flex min-w-0 items-center gap-1 rounded-full bg-red-400/10 px-2 py-0.5 text-xs text-red-400"
        >
          <Alert01Icon height={14} className="shrink-0" />
          <span className="truncate">{detail}</span>
        </span>
        {hint && (
          <span className="text-xs leading-relaxed text-zinc-500">{hint}</span>
        )}
      </div>
    );
  }
  const countLabel =
    showModelCount && outcome.modelCount > 0
      ? ` · ${outcome.modelCount} models`
      : "";
  return (
    <span className="flex min-w-0 items-center gap-1 rounded-full bg-emerald-400/10 px-2 py-0.5 text-xs text-emerald-400">
      <Tick02Icon height={14} className="shrink-0" />
      <span className="truncate">
        {savedLabel}
        {countLabel}
      </span>
    </span>
  );
}
