import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Cancel01Icon, SearchIcon } from "@icons";
import { useVirtualizer, type VirtualItem } from "@tanstack/react-virtual";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { handleSlashCommandKey } from "@/features/chat/hooks/useSlashCommandDropdownState";
import {
  useScrollSelectedToolIntoView,
  useSlashCommandItems,
} from "@/features/chat/hooks/useSlashCommandItems";
import type { SlashCommandMatch } from "@/features/chat/hooks/useSlashCommands";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { IntegrationsCard } from "@/features/integrations/components/IntegrationsCard";
import { usePathname } from "@/i18n/navigation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { useIntegrationsAccordion } from "@/stores/uiStore";

import { CategoryTabs } from "./CategoryTabs";
import { LockedCategorySection } from "./LockedCategorySection";
import { LockedToolItem } from "./LockedToolItem";
import type { VirtualItemType } from "./virtualItemTypes";

// Component to render each virtualized item
interface VirtualizedItemProps {
  virtualRow: VirtualItem;
  item: VirtualItemType;
  selectedIndex: number;
  selectedCategory: string;
  onSelect: (match: SlashCommandMatch) => void;
  onClose: () => void;
  measureElement: (element: HTMLElement | null) => void;
  categoryDisplayMap: Record<string, { displayName: string; iconUrl?: string }>;
  onIntegrationClick?: (integrationId: string) => void;
  openedViaButton?: boolean;
}

const VirtualizedItem: React.FC<VirtualizedItemProps> = ({
  virtualRow,
  item,
  selectedIndex,
  selectedCategory,
  onSelect,
  onClose,
  measureElement,
  categoryDisplayMap,
  onIntegrationClick,
  openedViaButton,
}) => {
  const baseStyle = {
    transform: `translateY(${virtualRow.start}px)`,
  };

  // IntegrationsCard
  if (item.type === "integrations-card") {
    return (
      <div
        data-index={virtualRow.index}
        ref={measureElement}
        className="absolute top-0 left-0 w-full"
        style={baseStyle}
      >
        <IntegrationsCard
          onClose={onClose}
          size="small"
          onIntegrationClick={onIntegrationClick}
        />
      </div>
    );
  }

  // Unlocked tool
  if (item.type === "unlocked-tool") {
    const { match, toolIndex } = item;
    const isSelected = toolIndex === selectedIndex;

    return (
      <div
        data-index={virtualRow.index}
        ref={measureElement}
        className="absolute top-0 left-0 w-full"
        style={baseStyle}
      >
        <button
          type="button"
          className={`relative mx-2 mb-1 block w-full cursor-pointer rounded-xl border-none text-left transition-colors duration-150 ${isSelected ? "bg-zinc-700/40" : "hover:bg-white/5"}`}
          onClick={() => {
            trackEvent(ANALYTICS_EVENTS.CHAT_SLASH_COMMAND_SELECTED, {
              tool_name: match.tool.name,
              tool_category: match.tool.category,
              opened_via_button: openedViaButton,
              // The typed filter query is user free text — intentionally not sent.
            });
            onSelect(match);
          }}
        >
          <div className="flex items-center gap-2 p-2">
            {/* Icon */}
            <div className="shrink-0">
              {getToolCategoryIcon(
                match.tool.category,
                { showBackground: false, size: 24 },
                categoryDisplayMap[match.tool.category]?.iconUrl,
              )}
            </div>

            {/* Content */}
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm text-foreground-600">
                  {formatToolName(match.tool.name)}
                </span>
                {selectedCategory === "all" && (
                  <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400 outline-1 outline-zinc-700">
                    {formatToolName(
                      categoryDisplayMap[match.tool.category]?.displayName ||
                        match.tool.category,
                    )}
                  </span>
                )}
              </div>
            </div>
          </div>
        </button>
      </div>
    );
  }

  // Locked category header
  if (item.type === "locked-category-header") {
    const { category, tools, requiredIntegration } = item;

    return (
      <div
        data-index={virtualRow.index}
        ref={measureElement}
        className="absolute top-0 left-0 w-full"
        style={baseStyle}
      >
        <div className="mt-2">
          <LockedCategorySection
            category={category}
            tools={tools}
            requiredIntegration={requiredIntegration}
            onConnect={onClose}
          />
        </div>
      </div>
    );
  }

  // Locked tool
  if (item.type === "locked-tool") {
    const { match } = item;

    return (
      <div
        data-index={virtualRow.index}
        ref={measureElement}
        className="absolute top-0 left-0 w-full"
        style={baseStyle}
      >
        <LockedToolItem tool={match.enhancedTool!} onConnect={onClose} />
      </div>
    );
  }

  return null;
};

/** Estimated row heights for the virtualizer (measureElement corrects them). */
function estimateVirtualItemHeight(
  index: number,
  virtualItems: VirtualItemType[],
): number {
  const item = virtualItems[index];
  if (!item) return 48;

  switch (item.type) {
    case "integrations-card":
      return 200; // Estimated height for IntegrationsCard (will auto-adjust)
    case "unlocked-tool":
      return 48; // Regular tool item height
    case "locked-category-header":
      return 80; // Category header with connect button
    case "locked-tool":
      return 48; // Locked tool item (same as regular)
    default:
      return 48;
  }
}

interface SlashCommandDropdownProps {
  matches: SlashCommandMatch[];
  selectedIndex: number;
  onSelect: (tool: SlashCommandMatch) => void;
  onClose: () => void;
  position: { top?: number; bottom?: number; left: number; width?: number };
  isVisible: boolean;
  openedViaButton?: boolean;
  selectedCategory?: string;
  categories?: string[];
  onCategoryChange?: (category: string) => void;
  onNavigateUp?: () => void;
  onNavigateDown?: () => void;
  onIntegrationClick?: (integrationId: string) => void;
}

const SlashCommandDropdown: React.FC<SlashCommandDropdownProps> = ({
  matches,
  selectedIndex,
  onSelect,
  onClose,
  position,
  isVisible,
  openedViaButton = false,
  selectedCategory: externalSelectedCategory,
  categories: externalCategories,
  onCategoryChange,
  onNavigateUp,
  onNavigateDown,
  onIntegrationClick,
}) => {
  const [searchQuery, setSearchQuery] = useState<string>("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const {
    isExpanded: isIntegrationsExpanded,
    setExpanded: setIntegrationsExpanded,
  } = useIntegrationsAccordion();

  // Determine max height based on current route
  const maxHeight = useMemo(() => {
    // Check if we're on a specific chat page (/c/:id)
    const isChatIdPage = pathname?.match(/^\/c\/[^/]+$/) && pathname !== "/c";
    return isChatIdPage ? "max-h-100" : "max-h-62";
  }, [pathname]);

  // Use external category state if provided, otherwise fall back to internal state
  const [internalSelectedCategory, setInternalSelectedCategory] =
    useState<string>("all");
  const selectedCategory = externalSelectedCategory ?? internalSelectedCategory;

  // Focus the dropdown when it becomes visible (only when opened via button)
  useEffect(() => {
    if (isVisible && openedViaButton && dropdownRef.current) {
      // Use requestAnimationFrame for better performance
      requestAnimationFrame(() => {
        dropdownRef.current?.focus();
      });
    }
  }, [isVisible, openedViaButton]);

  // Close integrations accordion when user starts searching
  useEffect(() => {
    if (searchQuery.trim() && isIntegrationsExpanded) {
      setIntegrationsExpanded(false);
    }
  }, [searchQuery, isIntegrationsExpanded, setIntegrationsExpanded]);

  const handleCategoryChange = (category: string) => {
    trackEvent(ANALYTICS_EVENTS.CHAT_SLASH_COMMAND_CATEGORY_CHANGED, {
      category,
      previous_category: selectedCategory,
    });
    if (onCategoryChange) {
      onCategoryChange(category);
    } else {
      setInternalSelectedCategory(category);
    }
  };

  // Handle keyboard navigation within the dropdown
  const handleKeyDown = (e: React.KeyboardEvent) => {
    handleSlashCommandKey(e, {
      matches,
      selectedCategory,
      categories,
      selectedIndex,
      selectCategory: handleCategoryChange,
      navigateUp: onNavigateUp,
      navigateDown: onNavigateDown,
      onSelect,
      onClose,
    });
  };

  // Get unique categories from matches, use external if provided
  const categories = useMemo(() => {
    if (externalCategories && externalCategories.length > 0) {
      return externalCategories;
    }
    const uniqueCategories = Array.from(
      new Set(matches.map((match) => match.tool.category)),
    );
    return ["all", ...uniqueCategories.toSorted()];
  }, [matches, externalCategories]);

  const {
    categoryDisplayMap,
    lockedCountByCategory,
    showIntegrationsCard,
    unlockedMatches,
    virtualItems,
  } = useSlashCommandItems({
    matches,
    selectedCategory,
    searchQuery,
    openedViaButton,
  });

  const rowVirtualizer = useVirtualizer({
    count: virtualItems.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: (index) => estimateVirtualItemHeight(index, virtualItems),
    overscan: 5,
  });

  useScrollSelectedToolIntoView({
    selectedIndex,
    unlockedMatchCount: unlockedMatches.length,
    showIntegrationsCard,
    isIntegrationsExpanded,
    virtualItems,
    scrollToIndex: rowVirtualizer.scrollToIndex,
  });

  return (
    <AnimatePresence>
      {isVisible && matches.length > 0 && (
        <m.div
          ref={dropdownRef}
          initial={{ opacity: 0, y: -8, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -8, scale: 0.95 }}
          transition={{
            duration: 0.2,
            ease: [0.19, 1, 0.22, 1],
          }}
          className="slash-command-dropdown fixed z-200 overflow-hidden rounded-3xl border-1 border-zinc-800 bg-zinc-900/70 outline-0! backdrop-blur-xl"
          style={{
            ...(position.top !== undefined && { top: 0, height: position.top }),
            ...(position.bottom !== undefined && {
              bottom: `calc(100vh - ${position.bottom - 2}px)`,
              maxHeight: position.bottom,
            }),
            left: position.left,
            width: position.width,
            transform: "none",
            boxShadow: "0px -18px 30px 5px rgba(0, 0, 0, 0.2)",
          }}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={handleKeyDown}
          tabIndex={-1}
        >
          {/* Header section - Only show when opened via button */}
          {openedViaButton && (
            <div className="flex items-center gap-2 p-3">
              {/* SearchIcon Input */}
              <div className="flex-1">
                <Input
                  type="text"
                  placeholder="Search tools..."
                  value={searchQuery}
                  radius="full"
                  startContent={<SearchIcon size={16} />}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
              {/* Close Button */}
              <Button
                onPress={onClose}
                isIconOnly
                size="sm"
                radius="full"
                variant="flat"
              >
                <Cancel01Icon size={14} />
              </Button>
            </div>
          )}

          {/* Category Tabs */}
          <CategoryTabs
            categories={categories}
            selectedCategory={selectedCategory}
            categoryDisplayMap={categoryDisplayMap}
            lockedCountByCategory={lockedCountByCategory}
            onCategoryChange={handleCategoryChange}
          />

          {/* Tool List */}
          <div
            ref={scrollContainerRef}
            className={`relative z-1 h-fit ${maxHeight} overflow-y-auto`}
          >
            <div className="py-2">
              {/* Single virtualized container for everything */}
              <div
                style={{
                  height: `${rowVirtualizer.getTotalSize()}px`,
                  width: "100%",
                  position: "relative",
                }}
              >
                {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                  const item = virtualItems[virtualRow.index];
                  if (!item) return null;

                  return (
                    <VirtualizedItem
                      key={virtualRow.key}
                      virtualRow={virtualRow}
                      item={item}
                      selectedIndex={selectedIndex}
                      selectedCategory={selectedCategory}
                      onSelect={onSelect}
                      onClose={onClose}
                      measureElement={rowVirtualizer.measureElement}
                      categoryDisplayMap={categoryDisplayMap}
                      onIntegrationClick={onIntegrationClick}
                      openedViaButton={openedViaButton}
                    />
                  );
                })}
              </div>
            </div>
          </div>
        </m.div>
      )}
    </AnimatePresence>
  );
};

export default SlashCommandDropdown;
