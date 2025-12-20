import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

interface ActionItemsIndicatorProps {
  steps: Array<{ category: string }>;
  iconSize?: number;
}

/**
 * Displays rotated tool category icons for workflow action items.
 * Reuses the icon display pattern from UnifiedWorkflowCard.
 */
export function ActionItemsIndicator({
  steps,
  iconSize = 16,
}: ActionItemsIndicatorProps) {
  const categories = [...new Set(steps.map((s) => s.category))];
  const displayIcons = categories.slice(0, 3);

  if (displayIcons.length === 0) return null;

  return (
    <div className="flex items-center -space-x-1.5">
      {displayIcons.map((category, index) => {
        const IconComponent = getToolCategoryIcon(category, {
          width: iconSize,
          height: iconSize,
        });
        return IconComponent ? (
          <div
            key={category}
            className="relative flex items-center justify-center"
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
      {categories.length > 3 && (
        <div className="z-[0] flex size-4 items-center justify-center rounded text-xs text-zinc-500">
          +{categories.length - 3}
        </div>
      )}
    </div>
  );
}
