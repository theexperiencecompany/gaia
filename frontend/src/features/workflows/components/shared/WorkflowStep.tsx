import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";

import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

interface WorkflowStepProps {
  step: {
    id: string;
    title: string;
    description: string;
    tool_name: string;
    tool_category: string;
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
      {/* Timeline dot with number */}
      <div
        className={`relative z-10 flex ${dotSize} flex-shrink-0 items-center justify-center rounded-full border-1 border-primary bg-primary/10 backdrop-blur-3xl`}
      >
        <span className={`${dotTextSize} font-semibold text-primary`}>
          {index + 1}
        </span>
      </div>

      {/* Step content */}
      <div className="flex-1 space-y-2">
        <div className="flex items-center gap-2">
          <Tooltip content="Tool Name" size={chipSize} color="foreground">
            <Chip
              radius="sm"
              variant="flat"
              className={`${chipPadding} pl-2 space-x-1 ${chipTextSize}`}
              startContent={getToolCategoryIcon(step.tool_category, {
                size: iconSize,
                width: iconSize,
                height: iconSize,
              })}
            >
              {formatToolName(step.tool_name)}
            </Chip>
          </Tooltip>
          <Tooltip content="Tool Category" size={chipSize} color="foreground">
            <Chip
              size={chipSize}
              variant="flat"
              color="primary"
              className="text-primary capitalize"
            >
              {step.tool_category
                .replaceAll("_", " ")
                .replace(
                  /^([a-zA-Z])([\s\S]*)$/,
                  (_, first, rest) => first.toUpperCase() + rest.toLowerCase(),
                )}
            </Chip>
          </Tooltip>
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
