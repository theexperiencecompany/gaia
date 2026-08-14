"use client";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrationLookup } from "@/features/integrations/hooks/useIntegrationLookup";
import {
  WORKFLOW_ICON_BG_ALPHA,
  WORKFLOW_ICON_MAP,
} from "../../constants/workflowIconCatalog";

interface WorkflowIconsProps {
  steps: Array<{ category: string }>;
  /** User-chosen icon slug — rendered in place of the step-category icons when set */
  icon?: string | null;
  /** Hex color for the user-chosen icon */
  iconColor?: string | null;
  iconSize?: number;
  maxIcons?: number;
  className?: string;
  spacing?: string;
  showBackground?: boolean;
}

/**
 * Displays workflow step category icons with rotated styling.
 * Reusable across UnifiedWorkflowCard and WorkflowsSidebar.
 */
export default function WorkflowIcons({
  steps,
  icon,
  iconColor,
  iconSize = 25,
  maxIcons = 3,
  className = "",
  spacing = "-space-x-1.5 ",
  showBackground = true,
}: WorkflowIconsProps) {
  const { getIntegrationIconUrl } = useIntegrationLookup();
  // De-duplicate categories, preserving first-seen order.
  const categories = [...new Set(steps.map((step) => step.category))];
  const displayIcons = categories.slice(0, maxIcons);

  // An explicitly chosen icon always wins over step-category icons. Gating it
  // on "no integrations" made rendering depend on the auth-gated integrations
  // catalog: icons flipped to tool icons (or blank, for internal categories)
  // the moment /integrations/me resolved, and public pages behaved differently
  // from the slug page, which renders the icon unconditionally.
  const customIcon = icon ? WORKFLOW_ICON_MAP.get(icon) : undefined;
  if (customIcon) {
    const CustomIcon = customIcon.Icon;
    const iconElement = (
      <CustomIcon
        size={iconSize}
        style={iconColor ? { color: iconColor } : undefined}
      />
    );
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
