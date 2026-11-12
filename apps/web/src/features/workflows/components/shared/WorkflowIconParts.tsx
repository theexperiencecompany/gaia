"use client";

import type { ReactNode } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrationLookup } from "@/features/integrations/hooks/useIntegrationLookup";
import { WORKFLOW_ICON_BG_ALPHA } from "../../constants/workflowIconStyle";

export interface StepCategoryIconsProps {
  steps: Array<{ category: string }>;
  iconSize: number;
  maxIcons: number;
  className: string;
  spacing: string;
  showBackground: boolean;
}

/** A workflow's chosen icon on its tinted tile. */
export function CustomIconTile({
  iconElement,
  iconColor,
  className,
  showBackground,
}: {
  iconElement: ReactNode;
  iconColor?: string | null;
  className: string;
  showBackground: boolean;
}) {
  return (
    <div className={`flex min-h-8 items-center ${className}`}>
      <div className="relative flex min-w-8 items-center justify-center">
        {showBackground ? (
          <div className="relative rounded-lg p-1">
            <div
              className="absolute inset-0 rounded-lg bg-zinc-700/60"
              style={
                iconColor
                  ? {
                      backgroundColor: `${iconColor}${WORKFLOW_ICON_BG_ALPHA}`,
                    }
                  : undefined
              }
            />
            <div className="relative">{iconElement}</div>
          </div>
        ) : (
          iconElement
        )}
      </div>
    </div>
  );
}

/** The de-duplicated step-category icons, rotated and stacked. */
export function StepCategoryIcons({
  steps,
  iconSize,
  maxIcons,
  className,
  spacing,
  showBackground,
}: StepCategoryIconsProps) {
  const { getIntegrationIconUrl } = useIntegrationLookup();
  // De-duplicate categories, preserving first-seen order.
  const categories = [...new Set(steps.map((step) => step.category))];
  const displayIcons = categories.slice(0, maxIcons);

  return (
    <div className={`flex min-h-8 items-center ${spacing} ${className}`}>
      {displayIcons.map((category, index) => {
        const IconComponent = getToolCategoryIcon(
          category,
          {
            width: iconSize,
            height: iconSize,
            showBackground: showBackground,
          },
          getIntegrationIconUrl(category),
        );
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
