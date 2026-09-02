import { Chip } from "@heroui/chip";

interface PricingCardHeaderProps {
  title: string;
  description?: string;
  isPro: boolean;
  isCurrentPlan: boolean;
}

/** Plan name, current-plan badge and description. */
export function PricingCardHeader({
  title,
  description,
  isPro,
  isCurrentPlan,
}: PricingCardHeaderProps) {
  return (
    <div className="flex flex-col gap-1.5 p-6 pb-4">
      {/* Reserve the same vertical space on both cards for the label row */}
      <div className="flex min-h-5 items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-2xl font-semibold">{title}</span>
          {isCurrentPlan && (
            <Chip className="text-xs" color="success" variant="flat">
              Current Plan
            </Chip>
          )}
        </div>
        {isPro && !isCurrentPlan && (
          <Chip
            className="text-xs font-medium tracking-wide text-primary"
            variant="flat"
            color="primary"
          >
            Popular
          </Chip>
        )}
      </div>

      {/* Description — always reserve two lines to keep cards aligned */}
      <p className="line-clamp-2 min-h-[2lh] text-sm font-light leading-relaxed text-zinc-400">
        {description ?? "\u00A0"}
      </p>
    </div>
  );
}
