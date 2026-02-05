"use client";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

interface WorkflowIconsProps {
  steps: Array<{ category: string }>;
  iconSize?: number;
  maxIcons?: number;
  className?: string;
}

/**
 * Displays workflow step category icons with rotated styling.
 * Reusable across UnifiedWorkflowCard and WorkflowsSidebar.
 */
export default function WorkflowIcons({
  steps,
  iconSize = 25,
  maxIcons = 3,
  className = "",
}: WorkflowIconsProps) {
  const categories = [...new Set(steps.map((step) => step.category))];
  const displayIcons = categories.slice(0, maxIcons);

  return (
    <div className={`flex min-h-8 items-center -space-x-1.5 ${className}`}>
      {displayIcons.map((category, index) => {
        const IconComponent = getToolCategoryIcon(category, {
          width: iconSize,
          height: iconSize,
        });
        return IconComponent ? (
          <div
            key={category}
            className="relative flex min-w-8 items-center justify-center"
            style={{
              rotate:
                displayIcons.length > 1
                  ? index % 2 === 0
                    ? "8deg"
                    : "-8deg"
                  : "0deg",
              zIndex: index,
            }}
          >
            {IconComponent}
          </div>
        ) : null;
      })}
      {categories.length > maxIcons && (
        <div
          className="z-0 flex items-center justify-center rounded-lg bg-zinc-700/60 text-foreground-500"
          style={{
            width: `${iconSize + 7}px`,
            height: `${iconSize + 7}px`,
            minWidth: `${iconSize + 7}px`,
            minHeight: `${iconSize + 7}px`,
            fontSize: `${Math.max(10, iconSize * 0.5)}px`,
          }}
        >
          +{categories.length - maxIcons}
        </div>
      )}
    </div>
  );
}
