"use client";

import { Chip } from "@heroui/react";
import { getToolDisplayName } from "@shared/icons";
import { shapeVariants } from "@/components/shared/shape";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrationLookup } from "@/features/integrations/hooks/useIntegrationLookup";

interface WorkflowStepProps {
  step: {
    id: string;
    title: string;
    description: string;
    category: string;
  };
  index: number;
  size?: "small" | "large";
}

export default function WorkflowStep({
  step,
  index,
  size = "small",
}: WorkflowStepProps) {
  const isLarge = size === "large";
  const { getIntegrationName, getIntegrationIconUrl } = useIntegrationLookup();

  // Size-dependent values
  const dotSize = isLarge ? "h-8 w-8" : "h-7 w-7";
  const dotTextSize = isLarge ? "text-sm" : "text-xs";
  const chipTextSize = isLarge ? "text-sm" : "text-xs";
  const chipHeight = isLarge ? "h-10" : "h-8";
  const iconSize = isLarge ? 22 : 17;
  const titleTextSize = isLarge ? "text-base" : "text-sm";
  const descriptionTextSize = isLarge ? "text-sm" : "text-xs";

  // Prefer the integration's real display name (handles custom/MCP ids that
  // would otherwise show a raw uuid); fall back to the category. Title-case the
  // result so lowercase custom names render capitalized.
  const categoryLabel =
    getIntegrationName(step.category) ?? getToolDisplayName(step.category);

  return (
    <div className="relative flex items-start gap-5">
      <div
        className={`relative z-10 mt-0.5 flex ${dotSize} shrink-0 items-center justify-center rounded-full bg-accent`}
      >
        <span className={`${dotTextSize} font-semibold text-black`}>
          {index + 1}
        </span>
      </div>

      <div className="flex-1 space-y-2">
        <div className="flex items-center gap-2">
          <Chip
            variant="soft"
            title={categoryLabel}
            aria-label={categoryLabel}
            className={shapeVariants({
              shape: "md",
              className: `${chipHeight} gap-1 truncate ${chipTextSize}`,
            })}
          >
            <div className="min-w-fit">
              {getToolCategoryIcon(
                step.category,
                {
                  size: iconSize,
                  width: iconSize,
                  height: iconSize,
                  showBackground: false,
                },
                getIntegrationIconUrl(step.category),
              )}
            </div>
            {categoryLabel}
          </Chip>
        </div>

        <div className="flex flex-col items-start">
          <h3
            className={`${titleTextSize} leading-relaxed font-medium text-zinc-100`}
          >
            {step.title}
          </h3>

          <p className={`${descriptionTextSize} leading-relaxed text-zinc-400`}>
            {step.description}
          </p>
        </div>
      </div>
    </div>
  );
}
