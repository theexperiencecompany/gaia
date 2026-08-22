"use client";

import { useEffect, useMemo } from "react";
import type { VirtualItemType } from "@/features/chat/components/composer/virtualItemTypes";
import type { SlashCommandMatch } from "@/features/chat/hooks/useSlashCommands";
import { formatToolName } from "@/features/chat/utils/chatUtils";

interface UseSlashCommandItemsParams {
  matches: SlashCommandMatch[];
  selectedCategory: string;
  searchQuery: string;
  openedViaButton: boolean;
}

/**
 * All list-building derivations behind the slash command dropdown: category
 * metadata, filtering by tab + search query, the unlocked/locked split, and
 * the flat virtualizer item list.
 */
export function useSlashCommandItems({
  matches,
  selectedCategory,
  searchQuery,
  openedViaButton,
}: UseSlashCommandItemsParams) {
  // Build a map of category ID -> { displayName, iconUrl } for efficient lookup
  const categoryDisplayMap = useMemo(() => {
    const map: Record<string, { displayName: string; iconUrl?: string }> = {};
    matches.forEach((match) => {
      if (!map[match.tool.category]) {
        map[match.tool.category] = {
          displayName: match.tool.display_name, // Single source of truth from backend
          iconUrl: match.tool.icon_url,
        };
      }
    });
    return map;
  }, [matches]);

  // Locked-tool count per category across all matches (drives the category tab
  // lock indicator independent of the currently selected category filter).
  const lockedCountByCategory = useMemo(() => {
    const counts: Record<string, number> = {};
    matches.forEach((match) => {
      if (match.enhancedTool?.isLocked) {
        counts[match.tool.category] = (counts[match.tool.category] ?? 0) + 1;
      }
    });
    return counts;
  }, [matches]);

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
          match.tool.category.toLowerCase().includes(query) ||
          match.tool.display_name?.toLowerCase().includes(query),
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

      // Add category header - use display_name directly from backend
      items.push({
        type: "locked-category-header",
        category,
        tools: categoryMatches,
        requiredIntegration: {
          id: firstTool.tool.category,
          name: firstTool.tool.display_name, // Single source of truth
        },
      });

      // Add each locked tool
      categoryMatches.forEach((match) => {
        items.push({ type: "locked-tool", match });
      });
    });

    return items;
  }, [showIntegrationsCard, unlockedMatches, lockedCategories]);

  return {
    categoryDisplayMap,
    lockedCountByCategory,
    filteredMatches,
    showIntegrationsCard,
    unlockedMatches,
    lockedCategories,
    virtualItems,
  };
}

interface ScrollSelectedToolParams {
  selectedIndex: number;
  unlockedMatchCount: number;
  showIntegrationsCard: boolean;
  isIntegrationsExpanded: boolean;
  virtualItems: VirtualItemType[];
  scrollToIndex: (
    index: number,
    options: { align: "center"; behavior: "smooth" },
  ) => void;
}

/** Scroll the highlighted tool row into view whenever the selection moves. */
export function useScrollSelectedToolIntoView({
  selectedIndex,
  unlockedMatchCount,
  showIntegrationsCard,
  isIntegrationsExpanded,
  virtualItems,
  scrollToIndex,
}: ScrollSelectedToolParams): void {
  useEffect(() => {
    if (selectedIndex >= 0 && selectedIndex < unlockedMatchCount) {
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
          scrollToIndex(virtualIndex, {
            align: "center",
            behavior: "smooth",
          });
        });
      }
    }
  }, [
    selectedIndex,
    unlockedMatchCount,
    showIntegrationsCard,
    isIntegrationsExpanded,
    virtualItems,
    scrollToIndex,
  ]);
}
