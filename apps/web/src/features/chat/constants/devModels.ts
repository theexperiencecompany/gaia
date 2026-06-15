/**
 * Dev-only model picker options (ENV=development).
 *
 * Lets developers force specific OpenRouter models for the comms and executor
 * agents independently, to benchmark which models perform best per task. The
 * backend only honors these when ENV=development; they are ignored in prod.
 *
 * `id === null` means "use the default model" (no override). All other ids are
 * raw OpenRouter model slugs sent verbatim to the backend.
 */

export interface DevModelOption {
  /** OpenRouter model slug, or null for the default (no override). */
  id: string | null;
  /** Short label shown in the dropdown. */
  label: string;
}

export const DEV_MODEL_OPTIONS: readonly DevModelOption[] = [
  { id: null, label: "Default" },
  { id: "deepseek/deepseek-v4-pro", label: "DeepSeek V4 Pro" },
  { id: "deepseek/deepseek-v4-flash", label: "DeepSeek V4 Flash" },
  { id: "moonshotai/kimi-k2.7-code", label: "Kimi K2.7 Code" },
  { id: "moonshotai/kimi-k2.6", label: "Kimi K2.6" },
  { id: "z-ai/glm-5.1", label: "GLM 5.1" },
  { id: "z-ai/glm-5", label: "GLM 5" },
  { id: "qwen/qwen3.7-max", label: "Qwen3.7 Max" },
  { id: "qwen/qwen3.6-max-preview", label: "Qwen3.6 Max" },
  { id: "x-ai/grok-4.3", label: "Grok 4.3" },
  { id: "x-ai/grok-4.20", label: "Grok 4.20" },
  { id: "minimax/minimax-m3", label: "MiniMax M3" },
] as const;

/** Look up a label for a stored model id; falls back to "Default". */
export function devModelLabel(id: string | null): string {
  return DEV_MODEL_OPTIONS.find((o) => o.id === id)?.label ?? "Default";
}
