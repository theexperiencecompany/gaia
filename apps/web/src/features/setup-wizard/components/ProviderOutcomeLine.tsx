import { Alert01Icon, Tick02Icon } from "@icons";
import type { ProviderTestResult } from "@/features/settings/api/providersApi";

interface ProviderOutcomeLineProps {
  outcome: ProviderTestResult | null;
  error: string | null;
  hint?: string | null;
  /** Label for a successful outcome — probed providers connect, others save. */
  savedLabel: string;
  showModelCount: boolean;
}

/** The inline result of a provider connect: the failure with its hint, or a success pill. */
export function ProviderOutcomeLine({
  outcome,
  error,
  hint,
  savedLabel,
  showModelCount,
}: ProviderOutcomeLineProps) {
  const failure =
    error ?? (outcome && !outcome.ok ? outcome.detail || "Test failed" : null);
  if (failure) {
    return (
      <div className="flex min-w-0 flex-col gap-1">
        <span
          title={failure}
          className="flex min-w-0 items-center gap-1 rounded-full bg-red-400/10 px-2 py-0.5 text-xs text-red-400"
        >
          <Alert01Icon height={14} className="shrink-0" />
          <span className="truncate">{failure}</span>
        </span>
        {hint && (
          <span className="text-xs leading-relaxed text-zinc-500">{hint}</span>
        )}
      </div>
    );
  }
  if (!outcome) return null;
  const modelCount = outcome.models.length;
  const countLabel =
    showModelCount && modelCount > 0 ? ` · ${modelCount} models` : "";
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
