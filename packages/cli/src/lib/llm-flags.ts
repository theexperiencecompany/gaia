/**
 * The `gaia up --llm-*` flags: which AI provider to save on first boot, and
 * the fields each one takes — the same fields its setup-wizard card accepts.
 *
 * The provider is saved through the API's own credential store (the path the
 * wizard and Settings write), by running `app.scripts.save_provider` inside
 * the running API container. The key travels in that process's environment,
 * never on a command line.
 * @module lib/llm-flags
 */

import * as path from "node:path";
import { runCommand } from "./child-process.js";
import { selfhostComposeArgs } from "./service-starter.js";

/** Every chat provider the API serves (LLMProviderName in apps/api/app/constants/llm.py). */
export const LLM_PROVIDERS = [
  "openrouter",
  "gemini",
  "openai",
  "ollama",
  "custom",
] as const;

export type LlmProvider = (typeof LLM_PROVIDERS)[number];

export interface LlmFlags {
  llmProvider?: LlmProvider;
  llmKey?: string;
  llmBaseUrl?: string;
  llmModel?: string;
}

type Need = "required" | "optional" | "unused";

interface ProviderFields {
  key: Need;
  baseUrl: Need;
  model: Need;
}

/** Mirrors each wizard card: keyed clouds take only a key, Ollama an endpoint, custom all three. */
const PROVIDER_FIELDS: Record<LlmProvider, ProviderFields> = {
  openrouter: { key: "required", baseUrl: "unused", model: "unused" },
  gemini: { key: "required", baseUrl: "unused", model: "unused" },
  openai: { key: "required", baseUrl: "unused", model: "unused" },
  ollama: { key: "unused", baseUrl: "optional", model: "optional" },
  custom: { key: "required", baseUrl: "required", model: "required" },
};

const FLAG_FOR: Record<keyof ProviderFields, string> = {
  key: "--llm-key",
  baseUrl: "--llm-base-url",
  model: "--llm-model",
};

function given(flags: LlmFlags, field: keyof ProviderFields): boolean {
  const value = {
    key: flags.llmKey,
    baseUrl: flags.llmBaseUrl,
    model: flags.llmModel,
  }[field];
  return value !== undefined && value !== "";
}

/**
 * Validate the flag combination before any side effect. Every failure names
 * the flag that fixes it — no silent defaults for secrets.
 */
export function validateLlmFlags(
  flags: LlmFlags & { noStart?: boolean },
): void {
  const fields = Object.keys(FLAG_FOR) as (keyof ProviderFields)[];
  if (!flags.llmProvider) {
    const stray = fields.find((field) => given(flags, field));
    if (stray) {
      throw new Error(
        `${FLAG_FOR[stray]} requires --llm-provider <${LLM_PROVIDERS.join("|")}>.`,
      );
    }
    return;
  }
  const provider = flags.llmProvider;
  for (const field of fields) {
    const need = PROVIDER_FIELDS[provider][field];
    if (need === "required" && !given(flags, field)) {
      throw new Error(
        `--llm-provider ${provider} requires ${FLAG_FOR[field]}.`,
      );
    }
    if (need === "unused" && given(flags, field)) {
      throw new Error(
        `${FLAG_FOR[field]} is not used with --llm-provider ${provider}.`,
      );
    }
  }
  if (flags.noStart) {
    throw new Error(
      "--llm-provider saves the provider into the running instance, so it cannot be combined with --no-start. Drop --no-start, or configure the provider in the web setup wizard later.",
    );
  }
}

/** Arguments for `python -m app.scripts.save_provider`; the key is never one of them. */
export function saveProviderArgs(
  flags: LlmFlags & { llmProvider: LlmProvider },
): string[] {
  const args = ["--provider", flags.llmProvider];
  if (flags.llmBaseUrl) args.push("--base-url", flags.llmBaseUrl);
  if (flags.llmModel) args.push("--model", flags.llmModel);
  return args;
}

/** The env var app.scripts.save_provider reads the key from. */
const API_KEY_ENV = "GAIA_PROVIDER_API_KEY";

/** How the finished screen names each provider. */
export const LLM_PROVIDER_NAMES: Record<LlmProvider, string> = {
  openrouter: "OpenRouter",
  gemini: "Gemini",
  openai: "OpenAI",
  ollama: "Ollama",
  custom: "custom provider",
};

/** save_provider's refusal line: "Could not save <provider>: <why>". */
const REFUSAL_RE = /Could not save \w+: (.+)/;

/**
 * Save the flagged provider into the running instance's credential store,
 * after the API's live probe accepted it (the probe the setup wizard runs).
 *
 * @throws Error whose message is the API's refusal alone, e.g. "OpenAI rejected the key: ...".
 */
export async function saveLlmProvider(
  repoPath: string,
  flags: LlmFlags & { llmProvider: LlmProvider },
): Promise<void> {
  const dockerDir = path.join(repoPath, "infra/docker");
  try {
    await runCommand(
      "docker",
      [
        ...selfhostComposeArgs(dockerDir),
        "exec",
        "-T",
        "-e",
        API_KEY_ENV,
        "gaia-backend",
        "python",
        "-m",
        "app.scripts.save_provider",
        ...saveProviderArgs(flags),
      ],
      { cwd: dockerDir, env: { [API_KEY_ENV]: flags.llmKey ?? "" } },
    );
  } catch (error) {
    const refusal = REFUSAL_RE.exec((error as Error).message)?.[1];
    if (refusal) throw new Error(refusal, { cause: error });
    throw error;
  }
}
