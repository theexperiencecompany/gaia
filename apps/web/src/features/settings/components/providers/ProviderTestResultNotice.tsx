import {
  getProviderErrorHint,
  type ProviderTestResult,
} from "@/features/settings/api/providersApi";

interface ProviderTestResultNoticeProps {
  result: ProviderTestResult;
  keyUrl: string;
}

export function ProviderTestResultNotice({
  result,
  keyUrl,
}: ProviderTestResultNoticeProps) {
  const hint = result.ok ? null : getProviderErrorHint(result.detail, keyUrl);

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
