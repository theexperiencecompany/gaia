import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Cancel01Icon, GridIcon, SearchIcon } from "@icons";
import { useVirtualizer, type VirtualItem } from "@tanstack/react-virtual";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SlashCommandMatch } from "@/features/chat/hooks/useSlashCommands";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { IntegrationsCard } from "@/features/integrations/components/IntegrationsCard";
import { usePathname } from "@/i18n/navigation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { useIntegrationsAccordion } from "@/stores/uiStore";

import { CategoryIntegrationStatus } from "./CategoryIntegrationStatus";
import { LockedCategorySection } from "./LockedCategorySection";
import { LockedToolItem } from "./LockedToolItem";

type VirtualItemType =
  | { type: "integrations-card" }
  | { type: "unlocked-tool"; match: SlashCommandMatch; toolIndex: number }
  | {
      type: "locked-category-header";
      category: string;
      tools: SlashCommandMatch[];
      requiredIntegration: { id: string; name: string };
    }
  | { type: "locked-tool"; match: SlashCommandMatch };

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
  if (item.type === "unlocked-tool") {
    const { match, toolIndex } = item;
    const isSelected = toolIndex === selectedIndex;
    const handleSelect = () => {
      trackEvent(ANALYTICS_EVENTS.CHAT_SLASH_COMMAND_SELECTED, {
        tool_name: match.tool.name,
        tool_category: match.tool.category,
        opened_via_button: openedViaButton,
      });
      onSelect(match);
    };
    return (
      <div
        data-index={virtualRow.index}
        ref={measureElement}
        className="absolute top-0 left-0 w-full"
        style={baseStyle}
      >
        <button
          type="button"
          className={`relative mx-2 mb-1 w-full cursor-pointer rounded-xl border-none bg-transparent p-0 text-left font-inherit transition-all duration-150 ${isSelected ? "bg-zinc-700/40" : "hover:bg-white/5"}`}
          onClick={handleSelect}
          onKeyDown={(event: React.KeyboardEvent<HTMLButtonElement>) => {
            if (event.key === "Enter" || event.key === " ") {
              event.stopPropagation();
            }
          }}
        >
          <div className="flex items-center gap-2 p-2">
            <div className="shrink-0">
              {getToolCategoryIcon(
                match.tool.category,
                { showBackground: false, size: 24 },
                categoryDisplayMap[match.tool.category]?.iconUrl,
              )}
            </div>
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

interface SlashDropdownHeaderProps {
  searchQuery: string;
  onSearchChange: (value: string) => void;
  onClose: () => void;
}

function SlashDropdownHeader({
  searchQuery,
  onSearchChange,
  onClose,
}: SlashDropdownHeaderProps) {
  return (
    <div className="flex items-center gap-2 p-3">
      <div className="flex-1">
        <Input
          type="text"
          placeholder="Search tools..."
          value={searchQuery}
          radius="full"
          startContent={<SearchIcon size={16} />}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>
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
  );
}

interface SlashDropdownCategoryTabsProps {
  categories: string[];
  selectedCategory: string;
  onCategoryChange: (category: string) => void;
  categoryDisplayMap: Record<string, { displayName: string; iconUrl?: string }>;
  lockedCountByCategory: Record<string, number>;
}

function SlashDropdownCategoryTabs({
  categories,
  selectedCategory,
  onCategoryChange,
  categoryDisplayMap,
  lockedCountByCategory,
}: SlashDropdownCategoryTabsProps) {
  return (
    <div>
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
              className={`flex cursor-pointer items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-all ${selectedCategory === category ? "bg-zinc-700/40 text-white" : "text-zinc-400 hover:bg-white/10 hover:text-zinc-300"}`}
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
    </div>
  );
}

interface SlashDropdownListProps {
  virtualItems: VirtualItemType[];
  selectedIndex: number;
  selectedCategory: string;
  maxHeight: string;
  onSelect: (match: SlashCommandMatch) => void;
  onClose: () => void;
  categoryDisplayMap: Record<string, { displayName: string; iconUrl?: string }>;
  onIntegrationClick?: (integrationId: string) => void;
  openedViaButton?: boolean;
  unlockedMatches: SlashCommandMatch[];
  showIntegrationsCard: boolean;
  isIntegrationsExpanded: boolean;
}

function SlashDropdownList({
  virtualItems,
  selectedIndex,
  selectedCategory,
  maxHeight,
  onSelect,
  onClose,
  categoryDisplayMap,
  onIntegrationClick,
  openedViaButton,
  unlockedMatches,
  showIntegrationsCard,
  isIntegrationsExpanded,
}: SlashDropdownListProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: virtualItems.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: (index) => {
      const item = virtualItems[index];
      if (!item) return 48;
      switch (item.type) {
        case "integrations-card":
          return 200;
        case "locked-category-header":
          return 80;
        default:
          return 48;
      }
    },
    overscan: 5,
  });
  useEffect(() => {
    if (selectedIndex >= 0 && selectedIndex < unlockedMatches.length) {
      if (showIntegrationsCard && isIntegrationsExpanded) {
        return;
      }
      let virtualIndex = -1;
      for (let i = 0; i < virtualItems.length; i++) {
        const item = virtualItems[i];
        if (item.type === "unlocked-tool" && item.toolIndex === selectedIndex) {
          virtualIndex = i;
          break;
        }
      }
      if (virtualIndex >= 0) {
        requestAnimationFrame(() => {
          rowVirtualizer.scrollToIndex(virtualIndex, {
            align: "center",
            behavior: "smooth",
          });
        });
      }
    }
  }, [
    selectedIndex,
    rowVirtualizer,
    unlockedMatches.length,
    showIntegrationsCard,
    isIntegrationsExpanded,
    virtualItems,
  ]);
  return (
    <div
      ref={scrollContainerRef}
      className={`relative z-1 h-fit ${maxHeight} overflow-y-auto`}
    >
      <div className="py-2">
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
  );
}

function useSlashCommandDerivedData({
  matches,
  selectedCategory,
  searchQuery,
  openedViaButton,
  externalCategories,
}: {
  matches: SlashCommandMatch[];
  selectedCategory: string;
  searchQuery: string;
  openedViaButton: boolean;
  externalCategories?: string[];
}) {
  const categories = useMemo(() => {
    if (externalCategories && externalCategories.length > 0) {
      return externalCategories;
    }
    const uniqueCategories = Array.from(
      new Set(matches.map((match) => match.tool.category)),
    );
    return ["all", ...uniqueCategories.toSorted()];
  }, [matches, externalCategories]);
  const categoryDisplayMap = useMemo(() => {
    const map: Record<string, { displayName: string; iconUrl?: string }> = {};
    matches.forEach((match) => {
      if (!map[match.tool.category]) {
        map[match.tool.category] = {
          displayName: match.tool.display_name,
          iconUrl: match.tool.icon_url,
        };
      }
    });
    return map;
  }, [matches]);
  const lockedCountByCategory = useMemo(() => {
    const counts: Record<string, number> = {};
    matches.forEach((match) => {
      if (match.enhancedTool?.isLocked) {
        counts[match.tool.category] = (counts[match.tool.category] ?? 0) + 1;
      }
    });
    return counts;
  }, [matches]);
  const filteredMatches = useMemo(() => {
    let filtered = matches;
    if (selectedCategory !== "all") {
      filtered = filtered.filter(
        (match) => match.tool.category === selectedCategory,
      );
    }
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      return filtered.filter(
        (match) =>
          formatToolName(match.tool.name).toLowerCase().includes(query) ||
          match.tool.category.toLowerCase().includes(query) ||
          match.tool.display_name?.toLowerCase().includes(query),
      );
    }
    return filtered;
  }, [matches, selectedCategory, searchQuery]);
  const showIntegrationsCard = useMemo(() => {
    if (!openedViaButton) return false;
    if (searchQuery.trim()) return false;
    return (
      selectedCategory === "all" && matches.length === filteredMatches.length
    );
  }, [
    selectedCategory,
    searchQuery,
    openedViaButton,
    matches.length,
    filteredMatches.length,
  ]);
  const { unlockedMatches, lockedCategories } = useMemo(() => {
    const unlocked: SlashCommandMatch[] = [];
    const lockedByCategory: Record<string, SlashCommandMatch[]> = {};
    filteredMatches.forEach((match) => {
      const isLocked = match.enhancedTool?.isLocked || false;
      if (isLocked) {
        if (!lockedByCategory[match.tool.category]) {
          lockedByCategory[match.tool.category] = [];
        }
        lockedByCategory[match.tool.category].push(match);
      } else {
        unlocked.push(match);
      }
    });
    return {
      unlockedMatches: unlocked,
      lockedCategories: lockedByCategory,
    };
  }, [filteredMatches]);
  const virtualItems = useMemo((): VirtualItemType[] => {
    const items: VirtualItemType[] = [];
    if (showIntegrationsCard) {
      items.push({ type: "integrations-card" });
    }
    unlockedMatches.forEach((match, index) => {
      items.push({ type: "unlocked-tool", match, toolIndex: index });
    });
    Object.entries(lockedCategories).forEach(([category, categoryMatches]) => {
      const firstTool = categoryMatches[0];
      items.push({
        type: "locked-category-header",
        category,
        tools: categoryMatches,
        requiredIntegration: {
          id: firstTool.tool.category,
          name: firstTool.tool.display_name,
        },
      });
      categoryMatches.forEach((match) => {
        items.push({ type: "locked-tool", match });
      });
    });
    return items;
  }, [showIntegrationsCard, unlockedMatches, lockedCategories]);
  return {
    categories,
    categoryDisplayMap,
    lockedCountByCategory,
    filteredMatches,
    showIntegrationsCard,
    unlockedMatches,
    lockedCategories,
    virtualItems,
  };
}

function useSlashCommandKeyboard({
  selectedCategory,
  categories,
  matches,
  selectedIndex,
  onCategoryChange,
  onNavigateUp,
  onNavigateDown,
  onSelect,
  onClose,
}: {
  selectedCategory: string;
  categories: string[];
  matches: SlashCommandMatch[];
  selectedIndex: number;
  onCategoryChange: (category: string) => void;
  onNavigateUp?: () => void;
  onNavigateDown?: () => void;
  onSelect: (tool: SlashCommandMatch) => void;
  onClose: () => void;
}) {
  return (e: React.KeyboardEvent) => {
    const getFilteredMatches = (
      category: string,
      list: SlashCommandMatch[],
    ) => {
      if (category === "all") return list;
      return list.filter((match) => match.tool.category === category);
    };
    const currentFilteredMatches = getFilteredMatches(
      selectedCategory,
      matches,
    );
    switch (e.key) {
      case "ArrowUp":
        e.preventDefault();
        if (onNavigateUp) onNavigateUp();
        break;
      case "ArrowDown":
        e.preventDefault();
        if (onNavigateDown) onNavigateDown();
        break;
      case "ArrowLeft": {
        e.preventDefault();
        const currentCategoryIndex = categories.indexOf(selectedCategory);
        const newLeftIndex = Math.max(0, currentCategoryIndex - 1);
        const newLeftCategory = categories[newLeftIndex];
        onCategoryChange(newLeftCategory);
        break;
      }
      case "ArrowRight": {
        e.preventDefault();
        const currentRightIndex = categories.indexOf(selectedCategory);
        const newRightIndex = Math.min(
          categories.length - 1,
          currentRightIndex + 1,
        );
        const newRightCategory = categories[newRightIndex];
        onCategoryChange(newRightCategory);
        break;
      }
      case "Enter":
      case "Tab": {
        e.preventDefault();
        const unlockedFilteredMatches = currentFilteredMatches.filter(
          (match) => !match.enhancedTool?.isLocked,
        );
        if (unlockedFilteredMatches.length === 1) {
          onSelect(unlockedFilteredMatches[0]);
        } else {
          const selectedMatch = currentFilteredMatches[selectedIndex];
          if (selectedMatch && !selectedMatch.enhancedTool?.isLocked) {
            onSelect(selectedMatch);
          }
        }
        break;
      }
      case "Escape":
        e.preventDefault();
        onClose();
        break;
      default:
        break;
    }
  };
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
  const pathname = usePathname();
  const {
    isExpanded: isIntegrationsExpanded,
    setExpanded: setIntegrationsExpanded,
  } = useIntegrationsAccordion();
  const maxHeight = useMemo(() => {
    const isChatIdPage = pathname?.match(/^\/c\/[^/]+$/) && pathname !== "/c";
    return isChatIdPage ? "max-h-100" : "max-h-62";
  }, [pathname]);
  const [internalSelectedCategory, setInternalSelectedCategory] =
    useState<string>("all");
  const selectedCategory = externalSelectedCategory ?? internalSelectedCategory;
  useEffect(() => {
    if (isVisible && openedViaButton && dropdownRef.current) {
      requestAnimationFrame(() => {
        dropdownRef.current?.focus();
      });
    }
  }, [isVisible, openedViaButton]);
  useEffect(() => {
    if (searchQuery.trim() && isIntegrationsExpanded) {
      setIntegrationsExpanded(false);
    }
  }, [searchQuery, isIntegrationsExpanded, setIntegrationsExpanded]);
  const {
    categories,
    categoryDisplayMap,
    lockedCountByCategory,
    showIntegrationsCard,
    unlockedMatches,
    virtualItems,
  } = useSlashCommandDerivedData({
    matches,
    selectedCategory,
    searchQuery,
    openedViaButton,
    externalCategories,
  });
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
  const handleKeyDown = useSlashCommandKeyboard({
    selectedCategory,
    categories,
    matches,
    selectedIndex,
    onCategoryChange: handleCategoryChange,
    onNavigateUp,
    onNavigateDown,
    onSelect,
    onClose,
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
          {openedViaButton && (
            <SlashDropdownHeader
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              onClose={onClose}
            />
          )}
          <SlashDropdownCategoryTabs
            categories={categories}
            selectedCategory={selectedCategory}
            onCategoryChange={handleCategoryChange}
            categoryDisplayMap={categoryDisplayMap}
            lockedCountByCategory={lockedCountByCategory}
          />
          <SlashDropdownList
            virtualItems={virtualItems}
            selectedIndex={selectedIndex}
            selectedCategory={selectedCategory}
            maxHeight={maxHeight}
            onSelect={onSelect}
            onClose={onClose}
            categoryDisplayMap={categoryDisplayMap}
            onIntegrationClick={onIntegrationClick}
            openedViaButton={openedViaButton}
            unlockedMatches={unlockedMatches}
            showIntegrationsCard={showIntegrationsCard}
            isIntegrationsExpanded={isIntegrationsExpanded}
          />
        </m.div>
      )}
    </AnimatePresence>
  );
};

export default SlashCommandDropdown;
