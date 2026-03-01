import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

interface TodoWorkflowCategoryIconsProps {
  categories: string[];
}

export default function TodoWorkflowCategoryIcons({
  categories,
}: TodoWorkflowCategoryIconsProps) {
  if (categories.length === 0) return null;

  return (
    <div className="flex min-h-8 items-center -space-x-1.5 self-center">
      {categories.slice(0, 3).map((category, index) => {
        const IconComponent = getToolCategoryIcon(category, {
          width: 22,
          height: 22,
        });
        return IconComponent ? (
          <div
            key={category}
            className="relative flex min-w-7 items-center justify-center"
            style={{
              rotate:
                categories.length > 1
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
        <div className="z-0 flex size-[28px] min-h-[28px] min-w-[28px] items-center justify-center rounded-lg bg-zinc-700/60 text-xs text-foreground-500">
          +{categories.length - 3}
        </div>
      )}
    </div>
  );
}
