import type { ProviderTestResult } from "@/features/settings/api/providersApi";

interface ProviderTestResultNoticeProps {
  result: ProviderTestResult;
  keyUrl: string | null;
}

/** A recovery hint for the failures the user can act on; the detail already says the rest. */
function failureHint(
  failure: ProviderTestResult["failure"],
  keyUrl: string | null,
): string | null {
  switch (failure) {
    case "auth_rejected":
      return keyUrl
        ? `Check your API key at ${keyUrl} — it may be expired or missing permissions.`
        : "Check your API key — it may be expired or missing permissions.";
    case "rate_limited":
      return "Rate limited — wait a minute and try again, or check your plan limits.";
    case "timeout":
      return "Provider didn't respond — check your network or try again.";
    default:
      return null;
  }
}

export function ProviderTestResultNotice({
  result,
  keyUrl,
}: ProviderTestResultNoticeProps) {
  const hint = failureHint(result.failure, keyUrl);

  return (
    <div
      className={`rounded-xl p-3 text-xs ${
        result.ok
          ? "bg-emerald-400/10 text-emerald-400"
          : "bg-red-400/10 text-red-400"
      }`}
    >
      <p>{result.detail}</p>
      {hint && (
        <p className="mt-1 text-xs leading-relaxed text-zinc-500">{hint}</p>
      )}
      {result.ok && result.models.length > 0 && (
        <p className="mt-1 text-zinc-400">
          {result.models.length} models available
        </p>
      )}
    </div>
  );
}
