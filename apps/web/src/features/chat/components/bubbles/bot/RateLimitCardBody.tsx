import { Alert01Icon, CheckmarkCircle02Icon, Clock01Icon } from "@icons";

const PRO_BENEFITS = [
  "Much higher limits on every feature",
  "Unlimited chat messages",
  "Priority responses and faster processing",
];

interface UpgradeRequiredBodyProps {
  featureName: string;
  planName: string;
  message?: string;
}

/** Plan-gated feature: explain the gate, then sell the plan. */
export function UpgradeRequiredBody({
  featureName,
  planName,
  message,
}: UpgradeRequiredBodyProps) {
  return (
    <>
      {/* Explanation — backend copy wins when provided (capped feature),
          otherwise the generic plan-gated copy applies. */}
      {message ? (
        <p className="text-xs leading-relaxed text-zinc-400">{message}</p>
      ) : (
        <p className="text-xs leading-relaxed text-zinc-400">
          <span className="font-medium text-zinc-200">{featureName}</span> is a{" "}
          <span className="font-medium text-warning-400">{planName}</span>{" "}
          feature and isn&apos;t included in your current plan. Upgrade to
          unlock it and get significantly higher limits across every feature.
        </p>
      )}

      {/* Benefits */}
      <div className="flex flex-col gap-1.5">
        {PRO_BENEFITS.map((benefit) => (
          <div key={benefit} className="flex items-start gap-2">
            <CheckmarkCircle02Icon className="mt-0.5 size-3.5 shrink-0 text-primary" />
            <span className="text-xs text-zinc-400">{benefit}</span>
          </div>
        ))}
      </div>
    </>
  );
}

interface DailyLimitBodyProps {
  featureName: string;
  isPro: boolean;
  resetInfo: { label: string; detail: string } | null;
}

/** Daily cap: say when it lifts, and nudge only when there is a tier above. */
export function DailyLimitBody({
  featureName,
  isPro,
  resetInfo,
}: DailyLimitBodyProps) {
  return (
    <>
      {/* What happened */}
      <p className="text-xs leading-relaxed text-zinc-400">
        You&apos;ve used all your{" "}
        <span className="font-medium text-zinc-200">{featureName}</span> calls
        for today. Your limit will automatically reset — no action needed.
      </p>

      {/* Reset time block */}
      {resetInfo && (
        <div className="flex items-center gap-3 rounded-xl bg-zinc-700 px-3 py-2.5">
          <Clock01Icon className="size-4 shrink-0 text-zinc-400" />
          <div className="flex flex-col gap-0.5">
            <span className="text-xs font-medium text-zinc-200">
              {resetInfo.label}
            </span>
            <span className="text-[11px] text-zinc-400">
              {resetInfo.detail}
            </span>
          </div>
        </div>
      )}

      {/* Upgrade nudge — hidden for users already on the top tier */}
      {!isPro && (
        <div className="flex items-start gap-2 px-3">
          <Alert01Icon className="mt-0.5 size-3.5 shrink-0 text-zinc-400" />
          <p className="text-xs text-zinc-400">
            Need more? Upgrade to{" "}
            <span className="font-medium text-zinc-300">Pro</span> for much
            higher limits on {featureName} and every other feature.
          </p>
        </div>
      )}
    </>
  );
}
