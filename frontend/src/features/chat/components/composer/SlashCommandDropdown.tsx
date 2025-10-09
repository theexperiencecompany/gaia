import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { AnimatePresence, motion } from "framer-motion";
import { Hash, Search, X } from "lucide-react";
import { usePathname } from "next/navigation";
import React, { useEffect, useMemo, useRef, useState } from "react";

import { SlashCommandMatch } from "@/features/chat/hooks/useSlashCommands";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { IntegrationsCard } from "@/features/integrations/components/IntegrationsCard";

import { CategoryIntegrationStatus } from "./CategoryIntegrationStatus";
import { LockedCategorySection } from "./LockedCategorySection";

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
  const itemRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const pathname = usePathname();

  // Determine max height based on current route
  const maxHeight = useMemo(() => {
    // Check if we're on a specific chat page (/c/:id)
    const isChatIdPage = pathname?.match(/^\/c\/[^\/]+$/) && pathname !== "/c";
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

  // Scroll to selected item when selectedIndex changes
  useEffect(() => {
    if (selectedIndex >= 0 && scrollContainerRef.current) {
      const selectedElement = itemRefs.current.get(selectedIndex);
      if (selectedElement) {
        const container = scrollContainerRef.current;
        const containerRect = container.getBoundingClientRect();
        const elementRect = selectedElement.getBoundingClientRect();

        // Check if element is fully visible
        const isElementAboveView = elementRect.top < containerRect.top;
        const isElementBelowView = elementRect.bottom > containerRect.bottom;

        if (isElementAboveView || isElementBelowView) {
          selectedElement.scrollIntoView({
            behavior: "smooth",
            block: "nearest",
            inline: "nearest",
          });
        }
      }
    }
  }, [selectedIndex]);

  const handleCategoryChange = (category: string) => {
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

      case "ArrowLeft":
        e.preventDefault();
        const currentCategoryIndex = categories.indexOf(selectedCategory);
        const newLeftIndex = Math.max(0, currentCategoryIndex - 1);
        const newLeftCategory = categories[newLeftIndex];
        handleCategoryChange(newLeftCategory);
        break;

      case "ArrowRight":
        e.preventDefault();
        const currentRightIndex = categories.indexOf(selectedCategory);
        const newRightIndex = Math.min(
          categories.length - 1,
          currentRightIndex + 1,
        );
        const newRightCategory = categories[newRightIndex];
        handleCategoryChange(newRightCategory);
        break;

      case "Enter":
      case "Tab":
        e.preventDefault();
        if (currentFilteredMatches.length === 1) {
          onSelect(currentFilteredMatches[0]);
        } else {
          const selectedMatch = currentFilteredMatches[selectedIndex];
          if (selectedMatch) {
            onSelect(selectedMatch);
          }
        }
        break;

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

  // Group tools by category and lock status
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
          className="slash-command-dropdown fixed z-[200] overflow-hidden rounded-3xl border-1 border-zinc-800 bg-zinc-900/70 outline-0! backdrop-blur-xl active:border-zinc-700"
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
              {/* Search Input */}
              <div className="flex-1">
                <Input
                  type="text"
                  placeholder="Search tools..."
                  value={searchQuery}
                  radius="full"
                  startContent={<Search size={16} />}
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
                <X size={14} />
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
                      <Hash
                        size={16}
                        strokeWidth={2}
                        className="text-gray-400"
                      />
                    ) : (
                      getToolCategoryIcon(category)
                    )}
                    <span>
                      {category === "all" ? "All" : formatToolName(category)}
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
              {/* Integrations Card - Only show in "all" category and when not filtering */}
              {selectedCategory === "all" &&
                (openedViaButton
                  ? !searchQuery.trim()
                  : matches.length === filteredMatches.length) && (
                  <IntegrationsCard onClose={onClose} />
                )}

              {/* Render unlocked tools first */}
              {unlockedMatches.map((match, index) => {
                // Calculate if this item should be highlighted
                // selectedIndex is based on filteredMatches (unlocked + locked), so we need to map correctly
                const isSelected = index === selectedIndex;

                return (
                  <div
                    key={match.tool.name}
                    ref={(el) => {
                      if (el) {
                        itemRefs.current.set(index, el);
                      } else {
                        itemRefs.current.delete(index);
                      }
                    }}
                    className={`relative mx-2 mb-1 cursor-pointer rounded-xl border-none transition-all duration-150 ${
                      isSelected ? "bg-zinc-700/40" : "hover:bg-white/5"
                    }`}
                    onClick={() => onSelect(match)}
                  >
                    <div className="flex items-center gap-2 p-2">
                      {/* Icon */}
                      <div className="flex-shrink-0">
                        {getToolCategoryIcon(match.tool.category)}
                      </div>

                      {/* Content */}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-sm text-foreground-600">
                            {formatToolName(match.tool.name)}
                          </span>
                          {selectedCategory === "all" && (
                            <span className="rounded-full bg-zinc-600 px-2 py-0.5 text-xs text-zinc-200">
                              {formatToolName(match.tool.category)}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}

              {/* Render locked categories as grouped sections */}
              {Object.entries(lockedCategories).map(
                ([category, categoryMatches]) => {
                  // Get integration info from the first tool in the category
                  const firstTool = categoryMatches[0];
                  const requiredIntegration =
                    firstTool.tool.required_integration;

                  if (!requiredIntegration) return null;

                  // Find integration name
                  const integrationName =
                    firstTool.enhancedTool?.integration?.integrationName ||
                    requiredIntegration;

                  return (
                    <LockedCategorySection
                      key={`locked-${category}`}
                      category={category}
                      tools={categoryMatches}
                      requiredIntegration={{
                        id: requiredIntegration,
                        name: integrationName,
                      }}
                      onConnect={onClose}
                    />
                  );
                },
              )}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default SlashCommandDropdown;
