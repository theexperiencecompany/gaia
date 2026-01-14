"use client";

import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

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

  // Size-dependent values
  const dotSize = isLarge ? "h-8 w-8" : "h-7 w-7";
  const dotTextSize = isLarge ? "text-sm" : "text-xs";
  const chipTextSize = isLarge ? "text-sm" : "text-xs";
  const chipPadding = isLarge ? "py-5!" : "py-4!";
  const iconSize = isLarge ? 22 : 17;
  const titleTextSize = isLarge ? "text-base" : "text-sm";
  const descriptionTextSize = isLarge ? "text-sm" : "text-xs";
  const chipSize = isLarge ? "md" : "sm";

  return (
    <div className="relative flex items-start gap-5">
      <div
        className={`relative z-10 flex ${dotSize} shrink-0 items-center justify-center rounded-full border-1 border-primary bg-primary/10 backdrop-blur-3xl`}
      >
        <span className={`${dotTextSize} font-semibold text-primary`}>
          {index + 1}
        </span>
      </div>

      <div className="flex-1 space-y-2">
        <div className="flex items-center gap-2">
          <Tooltip
            content={step.category
              .replaceAll("_", " ")
              .replace(
                /^([a-zA-Z])([\s\S]*)$/,
                (_: string, first: string, rest: string) =>
                  first.toUpperCase() + rest.toLowerCase(),
              )}
            size={chipSize}
            color="foreground"
            showArrow
          >
            <Chip
              radius="sm"
              variant="flat"
              className={`${chipPadding} pl-2 space-x-1 truncate ${chipTextSize}`}
              startContent={
                <div className="min-w-fit">
                  {getToolCategoryIcon(step.category, {
                    size: iconSize,
                    width: iconSize,
                    height: iconSize,
                  })}
                </div>
              }
            >
              {step.category
                .replaceAll("_", " ")
                .replace(/\b\w/g, (c) => c.toUpperCase())}
            </Chip>
          </Tooltip>
        </div>

        <div className="flex flex-col items-start">
          <h5
            className={`${titleTextSize} leading-relaxed font-medium text-foreground-100`}
          >
            {step.title}
          </h5>

          <p className={`${descriptionTextSize} leading-relaxed text-foreground-400`}>
            {step.description}
          </p>
        </div>
      </div>
    </div>
  );
}
