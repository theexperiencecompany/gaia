import { ScrollShadow } from "@heroui/scroll-shadow";
import { GridIcon } from "@icons";
import { getToolDisplayName } from "@shared/icons";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";

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
              <IntegrationIcon
                integrationId={category}
                iconUrl={categoryDisplayMap[category]?.iconUrl}
                size={16}
                showBackground
              />
            )}
            <span>
              {category === "all"
                ? "All"
                : (categoryDisplayMap[category]?.displayName ??
                  getToolDisplayName(category))}
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
