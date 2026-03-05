import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import {
  Alert01Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  UploadCircle01Icon,
} from "@icons";
import type { RateLimitData } from "@/config/registries/toolRegistry";
import { usePricingModalStore } from "@/stores/pricingModalStore";

interface RateLimitCardProps {
  data: RateLimitData;
}

function getResetInfo(
  resetTime?: string,
): { label: string; detail: string } | null {
  if (!resetTime) return null;
  const reset = new Date(resetTime);
  const diffMs = reset.getTime() - Date.now();
  if (diffMs <= 0)
    return {
      label: "Resets very soon",
      detail: "Your limit will refresh shortly.",
    };
  const diffMins = Math.ceil(diffMs / 60000);
  if (diffMins > 60) {
    const hours = Math.ceil(diffMins / 60);
    return {
      label: `Resets in ${hours} hour${hours !== 1 ? "s" : ""}`,
      detail: `Available again at ${reset.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
    };
  }
  return {
    label: `Resets in ${diffMins} minute${diffMins !== 1 ? "s" : ""}`,
    detail: `Available again at ${reset.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
  };
}

function formatFeatureName(feature?: string): string {
  if (!feature) return "This Feature";
  return feature
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

const PRO_BENEFITS = [
  "10x higher daily limits on all features",
  "Priority responses and faster processing",
];

export default function RateLimitCard({ data }: RateLimitCardProps) {
  const { feature, plan_required, reset_time } = data;
  const openPricingModal = usePricingModalStore((s) => s.openModal);
  const isUpgradeRequired = !!plan_required;
  const resetInfo = getResetInfo(reset_time);
  const featureName = formatFeatureName(feature);
  const planName = plan_required?.toUpperCase() ?? "PRO";

  return (
    <div className="flex w-full max-w-md flex-col gap-0 rounded-3xl bg-zinc-800 backdrop-blur-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 p-4 pb-3">
        <div className="flex items-center gap-3">
          <div
            className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${
              isUpgradeRequired ? "bg-warning/15" : "bg-red-500/15"
            }`}
          >
            {isUpgradeRequired ? (
              <UploadCircle01Icon className="size-5 text-warning-500" />
            ) : (
              <Clock01Icon className="size-5 text-red-400" />
            )}
          </div>

          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-semibold leading-tight text-zinc-100">
              {featureName}
            </span>
            <span className="text-xs text-zinc-500">
              {isUpgradeRequired
                ? `Requires ${planName} plan`
                : "Daily limit reached"}
            </span>
          </div>
        </div>

        <Chip
          size="sm"
          variant="flat"
          color={isUpgradeRequired ? "warning" : "danger"}
          classNames={{
            base: `shrink-0 ${isUpgradeRequired ? "bg-warning/15" : "bg-red-500/15"}`,
            content: "text-xs font-semibold",
          }}
        >
          {isUpgradeRequired ? planName : "Limit Hit"}
        </Chip>
      </div>

      <Divider className="bg-zinc-700/50" />

      {/* Body */}
      <div className="flex flex-col gap-3 p-4">
        {isUpgradeRequired ? (
          <>
            {/* Explanation */}
            <p className="text-xs leading-relaxed text-zinc-400">
              <span className="font-medium text-zinc-200">{featureName}</span>{" "}
              is a{" "}
              <span className="font-medium text-warning-400">{planName}</span>{" "}
              feature and isn&apos;t included in your current plan. Upgrade to
              unlock it and get significantly higher limits across every
              feature.
            </p>

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
        ) : (
          <>
            {/* What happened */}
            <p className="text-xs leading-relaxed text-zinc-400">
              You&apos;ve used all your{" "}
              <span className="font-medium text-zinc-200">{featureName}</span>{" "}
              calls for today. Your limit will automatically reset — no action
              needed.
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

            {/* Upgrade nudge */}
            <div className="flex items-start gap-2 px-3">
              <Alert01Icon className="mt-0.5 size-3.5 shrink-0 text-zinc-400" />
              <p className="text-xs text-zinc-400">
                Need more? Upgrade to{" "}
                <span className="font-medium text-zinc-300">PRO</span> for 10×
                higher daily limits on {featureName} and all other features.
              </p>
            </div>
          </>
        )}
      </div>

      <Divider className="bg-zinc-700/50" />

      {/* Footer CTA */}
      <div className="p-3">
        <Button
          size="sm"
          color="primary"
          variant={isUpgradeRequired ? "solid" : "flat"}
          onPress={openPricingModal}
          className="w-full rounded-xl font-medium"
        >
          {isUpgradeRequired ? `Upgrade to ${planName}` : "View Plans"}
        </Button>
      </div>
    </div>
  );
}
