"use client";

import { Chip } from "@heroui/chip";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrationLookup } from "@/features/integrations/hooks/useIntegrationLookup";

interface WorkflowStepProps {
  step: {
    id: string;
    title: string;
    description: string;
    category: string;
    icon_url?: string | null;
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
  const chipPadding = isLarge ? "py-5!" : "py-4!";
  const iconSize = isLarge ? 22 : 17;
  const titleTextSize = isLarge ? "text-base" : "text-sm";
  const descriptionTextSize = isLarge ? "text-sm" : "text-xs";

  // Prefer the integration's real display name (handles custom/MCP ids that
  // would otherwise show a raw uuid); fall back to a titleized category.
  const categoryLabel =
    step.category === "gaia"
      ? "GAIA"
      : (getIntegrationName(step.category) ??
        step.category
          .replaceAll("_", " ")
          .replace(/\b\w/g, (c) => c.toUpperCase()));

  return (
    <div className="relative flex items-start gap-5">
      <div
        className={`relative z-10 mt-0.5 flex ${dotSize} shrink-0 items-center justify-center rounded-full bg-primary`}
      >
        <span className={`${dotTextSize} font-semibold text-black`}>
          {index + 1}
        </span>
      </div>

      <div className="flex-1 space-y-2">
        <div className="flex items-center gap-2">
          <Chip
            radius="md"
            variant="flat"
            className={`${chipPadding} pl-2 space-x-1 truncate ${chipTextSize}`}
            startContent={
              <div className="min-w-fit">
                {getToolCategoryIcon(
                  step.category,
                  {
                    size: iconSize,
                    width: iconSize,
                    height: iconSize,
                    showBackground: false,
                  },
                  step.icon_url ?? getIntegrationIconUrl(step.category),
                )}
              </div>
            }
          >
            {categoryLabel}
          </Chip>
        </div>

        <div className="flex flex-col items-start">
          <h5
            className={`${titleTextSize} leading-relaxed font-medium text-zinc-100`}
          >
            {step.title}
          </h5>

          <p className={`${descriptionTextSize} leading-relaxed text-zinc-400`}>
            {step.description}
          </p>
        </div>
      </div>
    </div>
  );
}
