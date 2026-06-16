/**
 * Dev-only model picker options (ENV=development).
 *
 * Lets developers force specific models for the comms and executor agents
 * independently, to benchmark which models perform best per task. The backend
 * only honors these when ENV=development; they are ignored in prod.
 *
 * `id === null` means "use the default model" (no override). Every other option
 * carries an explicit `provider` (no guessing from the id shape) — the request
 * value is sent as "<provider>:<id>" and the backend routes accordingly.
 * Pricing is input / output per 1M tokens (OpenRouter live pricing; Gemini from
 * Google's list price) and shown as the dropdown item description.
 */

export type DevModelProvider = "gemini" | "openrouter";

export interface DevModelOption {
  /** Model id, or null for the default (no override). */
  id: string | null;
  /** Short label shown in the dropdown. */
  label: string;
  /** Backend provider to route through. Omitted for the default option. */
  provider?: DevModelProvider;
  /** Input / output price per 1M tokens, shown as the item description. */
  pricing?: string;
}

// OpenRouter models as compact [id, label, "input / output per 1M"] tuples —
// they all share provider "openrouter", so the builder below adds it once
// instead of repeating the field on every entry.
const OPENROUTER_MODELS: readonly (readonly [string, string, string])[] = [
  ["deepseek/deepseek-v4-pro", "DeepSeek V4 Pro", "$0.43 / $0.87 per 1M"],
  ["deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", "$0.10 / $0.20 per 1M"],
  ["moonshotai/kimi-k2.7-code", "Kimi K2.7 Code", "$0.75 / $3.50 per 1M"],
  ["moonshotai/kimi-k2.6", "Kimi K2.6", "$0.68 / $3.41 per 1M"],
  ["z-ai/glm-5.1", "GLM 5.1", "$0.98 / $3.08 per 1M"],
  ["z-ai/glm-5", "GLM 5", "$0.60 / $1.92 per 1M"],
  ["qwen/qwen3.7-max", "Qwen3.7 Max", "$1.25 / $3.75 per 1M"],
  ["qwen/qwen3.6-max-preview", "Qwen3.6 Max", "$1.04 / $6.24 per 1M"],
  ["x-ai/grok-4.3", "Grok 4.3", "$1.25 / $2.50 per 1M"],
  ["x-ai/grok-4.20", "Grok 4.20", "$1.25 / $2.50 per 1M"],
  ["minimax/minimax-m3", "MiniMax M3", "$0.30 / $1.20 per 1M"],
];

export const DEV_MODEL_OPTIONS: readonly DevModelOption[] = [
  { id: null, label: "Default" },
  {
    id: "gemini-3.1-flash-lite",
    label: "Gemini 3.1 Flash Lite",
    provider: "gemini",
    pricing: "$0.25 / $1.50 per 1M",
  },
  ...OPENROUTER_MODELS.map(
    ([id, label, pricing]): DevModelOption => ({
      id,
      label,
      provider: "openrouter",
      pricing,
    }),
  ),
];

/** Look up a label for a stored model id; falls back to "Default". */
export function devModelLabel(id: string | null): string {
  return DEV_MODEL_OPTIONS.find((o) => o.id === id)?.label ?? "Default";
}

/**
 * Build the backend request value for a stored model id: "<provider>:<id>", or
 * null for the default (no override). The backend parses the provider from it.
 */
export function devModelRequestValue(id: string | null): string | null {
  if (!id) return null;
  const opt = DEV_MODEL_OPTIONS.find((o) => o.id === id);
  if (!opt?.provider) return null;
  return `${opt.provider}:${opt.id}`;
}
