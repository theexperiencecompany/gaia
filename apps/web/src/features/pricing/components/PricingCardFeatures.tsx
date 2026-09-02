import { Tick02Icon } from "@icons";
import { PlanFeature } from "@/features/pricing/components/PlanFeature";

interface PricingCardFeaturesProps {
  features?: string[];
  featuresHeading?: string;
  isPro: boolean;
}

/** Ticked feature list — flex-1 so both cards fill remaining height equally. */
export function PricingCardFeatures({
  features,
  featuresHeading,
  isPro,
}: PricingCardFeaturesProps) {
  return (
    <div className="flex flex-1 flex-col gap-2.5 px-6 py-5">
      {!!featuresHeading && (
        <span className="mb-1 text-sm font-medium text-zinc-500">
          {featuresHeading}
        </span>
      )}
      {!!features &&
        features.map((feature) => (
          <div
            key={feature}
            className="flex items-start gap-3 text-sm font-light"
          >
            <Tick02Icon
              height="15"
              width="15"
              className={`mt-1 shrink-0 ${isPro ? "text-primary" : "text-zinc-500"}`}
            />
            <PlanFeature feature={feature} />
          </div>
        ))}
    </div>
  );
}
