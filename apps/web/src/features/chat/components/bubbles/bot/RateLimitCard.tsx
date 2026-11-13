import { Chip, Separator } from "@heroui/react";
import { Clock01Icon, UploadCircle01Icon } from "@icons";
import type { RateLimitData } from "@shared/chat";
import { separatorVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { useRateLimitCard } from "@/features/chat/hooks/useRateLimitCard";
import { DailyLimitBody, UpgradeRequiredBody } from "./RateLimitCardBody";

interface RateLimitCardProps {
  data: RateLimitData;
}

export default function RateLimitCard({ data }: RateLimitCardProps) {
  const {
    message,
    isUpgradeRequired,
    showUpgradeNudge,
    resetInfo,
    featureName,
    planName,
    showFooter,
    subtitle,
    openPlans,
  } = useRateLimitCard(data);

  return (
    <div className="flex w-full max-w-md flex-col gap-0 rounded-3xl bg-zinc-800 backdrop-blur-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 p-4 pb-3">
        <div className="flex items-center gap-3">
          <div
            className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${isUpgradeRequired ? "bg-warning/15" : "bg-red-500/15"}`}
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
            <span className="text-xs text-zinc-500">{subtitle}</span>
          </div>
        </div>

        <Chip
          size="sm"
          variant="soft"
          color={isUpgradeRequired ? "warning" : "danger"}
          className="shrink-0 text-xs font-semibold"
        >
          {isUpgradeRequired ? planName : "Limit Hit"}
        </Chip>
      </div>

      <Separator className={separatorVariants({ tone: "subtle" })} />

      {/* Body */}
      <div className="flex flex-col gap-3 p-4">
        {isUpgradeRequired ? (
          <UpgradeRequiredBody
            featureName={featureName}
            planName={planName}
            message={message}
          />
        ) : (
          <DailyLimitBody
            featureName={featureName}
            showUpgradeNudge={showUpgradeNudge}
            resetInfo={resetInfo}
            message={message}
          />
        )}
      </div>

      {showFooter && (
        <>
          <Separator className={separatorVariants({ tone: "subtle" })} />

          {/* Footer CTA */}
          <div className="p-3">
            <GaiaButton
              size="sm"
              variant={isUpgradeRequired ? "primary" : "accent-soft"}
              onPress={openPlans}
              className="w-full rounded-xl font-medium"
            >
              {isUpgradeRequired ? `Upgrade to ${planName}` : "View Plans"}
            </GaiaButton>
          </div>
        </>
      )}
    </div>
  );
}
