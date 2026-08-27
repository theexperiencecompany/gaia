import { ScrollShadow } from "@heroui/scroll-shadow";
import { GridIcon } from "@icons";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

import { CategoryIntegrationStatus } from "./CategoryIntegrationStatus";

interface CategoryTabsProps {
  categories: string[];
  selectedCategory: string;
  categoryDisplayMap: Record<string, { displayName: string; iconUrl?: string }>;
  lockedCountByCategory: Record<string, number>;
  onCategoryChange: (category: string) => void;
}

/** The horizontal category tab row at the top of the slash command dropdown. */
export function CategoryTabs({
  categories,
  selectedCategory,
  categoryDisplayMap,
  lockedCountByCategory,
  onCategoryChange,
}: CategoryTabsProps) {
  return (
    <ScrollShadow orientation="horizontal" className="overflow-x-auto">
      <div className="flex min-w-max gap-1 px-2 py-2">
        {categories.map((category) => (
          <button
            type="button"
            key={category}
            onClick={(e) => {
              e.stopPropagation();
              onCategoryChange(category);
            }}
            className={`flex cursor-pointer items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-colors ${selectedCategory === category ? "bg-zinc-700/40 text-white" : "text-zinc-400 hover:bg-white/10 hover:text-zinc-300"}`}
          >
            {category === "all" ? (
              <GridIcon size={16} strokeWidth={2} className="text-gray-400" />
            ) : (
              getToolCategoryIcon(
                category,
                { showBackground: false, size: 16 },
                categoryDisplayMap[category]?.iconUrl,
              )
            )}
            <span>
              {category === "all"
                ? "All"
                : formatToolName(
                    categoryDisplayMap[category]?.displayName || category,
                  )}
            </span>
            <CategoryIntegrationStatus
              category={category}
              lockedCount={lockedCountByCategory[category] ?? 0}
            />
          </button>
        ))}
      </div>
    </ScrollShadow>
  );
}
