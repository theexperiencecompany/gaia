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
import { Link } from "@heroui/link";
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
import CopyButton from "@/components/ui/CopyButton";
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
              label="API key"
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
              <Link
                href={PROVIDER_KEY_URLS[config.key] as string}
                isExternal
                size="sm"
                className="inline-flex items-center gap-1 text-xs text-zinc-500"
              >
                Get your key
                <SquareArrowUpRight02Icon size={12} />
              </Link>
            )}
          </>
        )}
        {config.showBaseUrl && (
          <Input
            label="Base URL"
            placeholder={
              config.defaultBaseUrl || "https://your-gateway.example.com/v1"
            }
            value={baseUrl}
            onValueChange={setBaseUrl}
            size="sm"
            radius="md"
            isDisabled={isBusy}
          />
        )}
        {config.showModel && (
          <Input
            label="Model"
            placeholder="Default"
            description="Leave empty to use the endpoint default."
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
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);

  const handleOllamaOneClick = async () => {
    setOllamaBusy(true);
    setOllamaOutcome(null);
    setOllamaError(null);
    setOllamaModels([]);
    const body = {
      base_url: config.defaultBaseUrl || OLLAMA_ONE_CLICK.baseUrl,
      model: config.defaultModel || OLLAMA_ONE_CLICK.model,
    };
    try {
      // Probe first, save second: an unreachable endpoint must not flip the
      // wizard to "ready".
      const test = await providersApi.testProvider("ollama", body);
      if (!test.ok) {
        setOllamaOutcome({
          ok: false,
          detail: test.detail,
          modelCount: test.models?.length ?? 0,
        });
        return;
      }
      await providersApi.upsertProvider("ollama", body);
      setOllamaModels(test.models ?? []);
      setOllamaOutcome({
        ok: true,
        detail: test.detail,
        modelCount: test.models?.length ?? 0,
      });
      onSaved();
    } catch (err) {
      setOllamaError(
        extractProviderError(err) ??
          "Couldn't reach GAIA to save — check your connection and try again. Your key wasn't stored.",
      );
    } finally {
      setOllamaBusy(false);
    }
  };

  const hint = (() => {
    if (ollamaError) return getProviderErrorHint(ollamaError, "ollama");
    if (ollamaOutcome && !ollamaOutcome.ok)
      return getProviderErrorHint(ollamaOutcome.detail, "ollama");
    if (ollamaOutcome?.ok && ollamaModels.length > 0) {
      const wanted = config.defaultModel || OLLAMA_ONE_CLICK.model;
      const pulled = ollamaModels.some(
        (m) =>
          m === wanted || m.endsWith(`:${wanted}`) || wanted.endsWith(`:${m}`),
      );
      if (!pulled)
        return (
          `Connected, but ${wanted} isn't pulled yet — ` +
          `run ollama pull ${wanted}, then chat.`
        );
    }
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
        Requires Ollama running on your host —{" "}
        <Link
          href="https://ollama.com"
          isExternal
          size="sm"
          className="text-xs"
        >
          ollama.com <SquareArrowUpRight02Icon size={10} />
        </Link>
      </p>
      <div className="mt-2 flex items-center gap-2 rounded-xl bg-zinc-800 py-1 pr-1 pl-3">
        <code className="min-w-0 flex-1 truncate font-mono text-xs text-zinc-300">
          ollama pull {OLLAMA_ONE_CLICK.model} && ollama serve
        </code>
        <CopyButton
          textToCopy={`ollama pull ${OLLAMA_ONE_CLICK.model} && ollama serve`}
          variant="light"
          size="sm"
          className="shrink-0 text-zinc-400"
        />
      </div>
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
