"use client";

import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import { SquareArrowUpRight02Icon } from "@icons";
import CopyButton from "@/components/ui/CopyButton";
import {
  getProviderErrorHint,
  type ProviderTestResult,
} from "@/features/settings/api/providersApi";
import { useProviderConnect } from "@/features/settings/hooks/useProviderConnect";
import type { ProviderCard } from "../utils/providerCards";
import { ProviderOutcomeLine } from "./ProviderOutcomeLine";

interface OllamaOneClickProps {
  config: ProviderCard;
  parentBusy: boolean;
  onSaved: () => void;
}

/** What to tell the user after a one-click attempt, including a model that is not pulled yet. */
function ollamaHint(
  config: ProviderCard,
  outcome: ProviderTestResult | null,
  error: string | null,
): string | null {
  const failure = error ?? (outcome && !outcome.ok ? outcome.detail : null);
  if (failure) return getProviderErrorHint(failure, config.key_url);
  if (!outcome?.ok || outcome.models.length === 0) return null;
  const wanted = config.default_model;
  const pulled = outcome.models.some(
    (m) => m === wanted || m.endsWith(`:${wanted}`) || wanted.endsWith(`:${m}`),
  );
  return pulled
    ? null
    : `Connected, but ${wanted} isn't pulled yet — run ollama pull ${wanted}, then chat.`;
}

export function OllamaOneClick({
  config,
  parentBusy,
  onSaved,
}: OllamaOneClickProps) {
  const { isBusy, outcome, error, connect } = useProviderConnect("ollama", {
    connectionTestable: true,
    onSaved,
  });
  const command = `ollama pull ${config.default_model} && ollama serve`;

  return (
    <div className="mb-3 rounded-xl bg-zinc-800 p-3">
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
          isLoading={isBusy}
          isDisabled={isBusy || parentBusy}
          onPress={() =>
            void connect({
              base_url: config.base_url,
              model: config.default_model,
            })
          }
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
      <div className="mt-2 flex items-center gap-2 rounded-xl bg-zinc-900 py-1 pr-1 pl-3">
        <code className="min-w-0 flex-1 truncate font-mono text-xs text-zinc-300">
          {command}
        </code>
        <CopyButton
          textToCopy={command}
          variant="light"
          size="sm"
          className="shrink-0 text-zinc-400"
        />
      </div>
      {(outcome || error) && (
        <div className="mt-2">
          <ProviderOutcomeLine
            outcome={outcome}
            error={error}
            hint={ollamaHint(config, outcome, error)}
            savedLabel="Saved"
            showModelCount={false}
          />
        </div>
      )}
    </div>
  );
}
