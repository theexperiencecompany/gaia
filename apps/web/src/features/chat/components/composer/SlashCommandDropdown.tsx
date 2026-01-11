import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { useVirtualizer, type VirtualItem } from "@tanstack/react-virtual";
import { AnimatePresence, motion } from "framer-motion";
import { usePathname } from "next/navigation";
import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { SlashCommandMatch } from "@/features/chat/hooks/useSlashCommands";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { IntegrationsCard } from "@/features/integrations/components/IntegrationsCard";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { Cancel01Icon, GridIcon, SearchIcon } from "@/icons";
import { posthog } from "@/lib/posthog";
import { useIntegrationsAccordion } from "@/stores/uiStore";

import { CategoryIntegrationStatus } from "./CategoryIntegrationStatus";
import { LockedCategorySection } from "./LockedCategorySection";
import { LockedToolItem } from "./LockedToolItem";

// Types for virtualized items
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

// Component to render each virtualized item
interface VirtualizedItemProps {
  virtualRow: VirtualItem;
  item: VirtualItemType;
  selectedIndex: number;
  selectedCategory: string;
  openedViaButton: boolean;
  searchQuery: string;
  onSelect: (match: SlashCommandMatch) => void;
  onClose: () => void;
  measureElement: (element: HTMLElement | null) => void;
  categoryDisplayMap: Record<string, { displayName: string; iconUrl?: string }>;
}

const VirtualizedItem: React.FC<VirtualizedItemProps> = ({
  virtualRow,
  item,
  selectedIndex,
  selectedCategory,
  openedViaButton,
  searchQuery,
  onSelect,
  onClose,
  measureElement,
  categoryDisplayMap,
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
        <IntegrationsCard onClose={onClose} size="small" />
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
        <div
          className={`relative mx-2 mb-1 cursor-pointer rounded-xl border-none transition-all duration-150 ${
            isSelected ? "bg-zinc-700/40" : "hover:bg-white/5"
          }`}
          onClick={() => {
            posthog.capture("chat:slash_command_selected", {
              tool_name: match.tool.name,
              tool_category: match.tool.category,
              opened_via_button: openedViaButton,
              search_query: searchQuery || null,
            });
            onSelect(match);
          }}
        >
          <div className="flex items-center gap-2 p-2">
            {/* Icon */}
            <div className="flex-shrink-0">
              {getToolCategoryIcon(
                match.tool.category,
                {},
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
        </div>
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

  // Get integrations to look up custom names/icons
  const { integrations } = useIntegrations();

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
    posthog.capture("chat:slash_command_category_changed", {
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
    // Get filtered matches based on current category
    const getFilteredMatches = (
      category: string,
      matches: SlashCommandMatch[],
    ) => {
      if (category === "all") return matches;
      return matches.filter((match) => match.tool.category === category);
    };

    const currentFilteredMatches = getFilteredMatches(
      selectedCategory,
      matches,
    );

    switch (e.key) {
      case "ArrowUp":
        e.preventDefault();
        if (onNavigateUp) {
          onNavigateUp();
        }
        break;

      case "ArrowDown":
        e.preventDefault();
        if (onNavigateDown) {
          onNavigateDown();
        }
        break;

      case "ArrowLeft": {
        e.preventDefault();
        const currentCategoryIndex = categories.indexOf(selectedCategory);
        const newLeftIndex = Math.max(0, currentCategoryIndex - 1);
        const newLeftCategory = categories[newLeftIndex];
        handleCategoryChange(newLeftCategory);
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
        handleCategoryChange(newRightCategory);
        break;
      }

      case "Enter":
      case "Tab": {
        e.preventDefault();
        // Only select unlocked items
        const unlockedFilteredMatches = currentFilteredMatches.filter(
          (match) => !match.enhancedTool?.isLocked,
        );
        if (unlockedFilteredMatches.length === 1) {
          onSelect(unlockedFilteredMatches[0]);
        } else {
          const selectedMatch = currentFilteredMatches[selectedIndex];
          // Only allow selection if the item is not locked
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

  // Get unique categories from matches, use external if provided
  const categories = useMemo(() => {
    if (externalCategories && externalCategories.length > 0) {
      return externalCategories;
    }
    const uniqueCategories = Array.from(
      new Set(matches.map((match) => match.tool.category)),
    );
    return ["all", ...uniqueCategories.sort()];
  }, [matches, externalCategories]);

  // Build a map of category ID -> { displayName, iconUrl } for efficient lookup
  const categoryDisplayMap = useMemo(() => {
    const map: Record<string, { displayName: string; iconUrl?: string }> = {};
    matches.forEach((match) => {
      if (!map[match.tool.category]) {
        // First try to find matching integration if tool requires one (which custom MCPs do)
        const integrationId =
          match.tool.required_integration || match.tool.category;
        const integration = integrations?.find((i) => i.id === integrationId);

        map[match.tool.category] = {
          displayName:
            integration?.name ||
            match.tool.integration_name ||
            match.tool.category_display_name ||
            match.tool.category,
          iconUrl: integration?.iconUrl || match.tool.icon_url,
        };
      }
    });
    return map;
  }, [matches, integrations]);

  // Filter matches based on selected category and search query
  const filteredMatches = useMemo(() => {
    let filtered = matches;

    // Filter by category
    if (selectedCategory !== "all") {
      filtered = filtered.filter(
        (match) => match.tool.category === selectedCategory,
      );
    }

    // Filter by search query (when opened via button or slash command)
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      return filtered.filter(
        (match) =>
          formatToolName(match.tool.name).toLowerCase().includes(query) ||
          match.tool.category.toLowerCase().includes(query),
      );
    }

    return filtered;
  }, [matches, selectedCategory, searchQuery]);

  // Check if IntegrationsCard should be shown
  const showIntegrationsCard = useMemo(() => {
    // Only show integrations card when opened via button (not via typing slash)
    if (!openedViaButton) return false;

    // Hide when searching in the search input
    if (searchQuery.trim()) return false;

    // Show only for "all" category and when no filtering is happening
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

  // Separate unlocked and locked matches, grouping locked by category
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

  // Build flat list of virtualized items
  const virtualItems = useMemo((): VirtualItemType[] => {
    const items: VirtualItemType[] = [];

    // Add IntegrationsCard if shown
    if (showIntegrationsCard) {
      items.push({ type: "integrations-card" });
    }

    // Add unlocked tools
    unlockedMatches.forEach((match, index) => {
      items.push({ type: "unlocked-tool", match, toolIndex: index });
    });

    // Add locked categories with their tools
    Object.entries(lockedCategories).forEach(([category, categoryMatches]) => {
      const firstTool = categoryMatches[0];
      const requiredIntegration = firstTool.tool.required_integration;

      if (!requiredIntegration) return;

      const integrationName =
        firstTool.enhancedTool?.integration?.integrationName ||
        requiredIntegration;

      // Add category header
      items.push({
        type: "locked-category-header",
        category,
        tools: categoryMatches,
        requiredIntegration: {
          id: requiredIntegration,
          name: integrationName,
        },
      });

      // Add each locked tool
      categoryMatches.forEach((match) => {
        items.push({ type: "locked-tool", match });
      });
    });

    return items;
  }, [showIntegrationsCard, unlockedMatches, lockedCategories]);

  const rowVirtualizer = useVirtualizer({
    count: virtualItems.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: (index) => {
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
    },
    overscan: 5,
  });

  // Scroll to selected item when selectedIndex changes
  useEffect(() => {
    if (selectedIndex >= 0 && selectedIndex < unlockedMatches.length) {
      // Don't scroll if IntegrationsCard is shown and expanded
      // This keeps the integrations visible while navigating tools
      if (showIntegrationsCard && isIntegrationsExpanded) {
        return;
      }

      // Find the virtual index for the selected unlocked tool
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
    <AnimatePresence>
      {isVisible && matches.length > 0 && (
        <motion.div
          ref={dropdownRef}
          initial={{ opacity: 0, y: -8, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -8, scale: 0.95 }}
          transition={{
            duration: 0.2,
            ease: [0.19, 1, 0.22, 1],
          }}
          className="slash-command-dropdown fixed z-[200] overflow-hidden rounded-3xl border-1 border-zinc-800 bg-zinc-900/70 outline-0! backdrop-blur-xl"
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
          <div>
            <ScrollShadow orientation="horizontal" className="overflow-x-auto">
              <div className="flex min-w-max gap-1 px-2 py-2">
                {/* <div className="grid min-w-max gap-1 px-2 py-2 grid-rows-2 grid-flow"> for 2 rows */}
                {categories.map((category) => (
                  <button
                    type="button"
                    key={category}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCategoryChange(category);
                    }}
                    className={`flex cursor-pointer items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-all ${
                      selectedCategory === category
                        ? "bg-zinc-700/40 text-white"
                        : "text-zinc-400 hover:bg-white/10 hover:text-zinc-300"
                    }`}
                  >
                    {category === "all" ? (
                      <GridIcon
                        size={16}
                        strokeWidth={2}
                        className="text-gray-400"
                      />
                    ) : (
                      getToolCategoryIcon(
                        category,
                        {},
                        categoryDisplayMap[category]?.iconUrl,
                      )
                    )}
                    <span>
                      {category === "all"
                        ? "All"
                        : formatToolName(
                            categoryDisplayMap[category]?.displayName ||
                              category,
                          )}
                    </span>
                    <CategoryIntegrationStatus category={category} />
                  </button>
                ))}
              </div>
            </ScrollShadow>
          </div>

          {/* Tool List */}
          <div
            ref={scrollContainerRef}
            className={`relative z-[1] h-fit ${maxHeight} overflow-y-auto`}
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
                      openedViaButton={openedViaButton}
                      searchQuery={searchQuery}
                      onSelect={onSelect}
                      onClose={onClose}
                      measureElement={rowVirtualizer.measureElement}
                      categoryDisplayMap={categoryDisplayMap}
                    />
                  );
                })}
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default SlashCommandDropdown;
