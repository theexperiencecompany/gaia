import {
  INTEGRATION_STATE_ORDER,
  integrationConnectionState,
} from "@shared/utils";
import { useMemo } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import {
  ALL_CATEGORIES,
  getUniqueCategories,
  sortCategories,
} from "../constants/categories";
import type { Integration } from "../types";
import { useIntegrationSearch } from "./useIntegrationSearch";
import { useIntegrations } from "./useIntegrations";

interface UseIntegrationsListParams {
  searchQuery: string;
  selectedCategory: string;
  onIntegrationClick?: (integrationId: string) => void;
}

export function useIntegrationsList({
  searchQuery,
  selectedCategory,
  onIntegrationClick,
}: UseIntegrationsListParams) {
  const { integrations, isPending, connectIntegration } = useIntegrations();
  const currentUserId = useCurrentUser().userId;

  const { filteredIntegrations } = useIntegrationSearch(
    integrations,
    searchQuery,
    selectedCategory,
  );

  const handleConnect = async (integrationId: string) => {
    const integration = integrations.find((i) => i.id === integrationId);
    // API-key (bearer) integrations collect their key in the detail sidebar —
    // open it instead of connecting directly (same as clicking the row).
    if (integration?.authType === "bearer" && integration.requiresAuth) {
      onIntegrationClick?.(integrationId);
      return;
    }
    try {
      await connectIntegration(integrationId);
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  // Derive categories from backend integrations data
  const availableCategories = useMemo(() => {
    const uniqueCategories = getUniqueCategories(integrations);
    const sorted = sortCategories(uniqueCategories);
    // Add "created_by_you" at the start if user has custom integrations they created
    const hasCreatedByYou = integrations.some(
      (i) => i.createdBy === currentUserId,
    );
    if (hasCreatedByYou) {
      return ["created_by_you", ...sorted];
    }
    return sorted;
  }, [integrations, currentUserId]);

  // Integrations created by the current user
  const createdByYouIntegrations = useMemo(() => {
    return filteredIntegrations.filter((i) => i.createdBy === currentUserId);
  }, [filteredIntegrations, currentUserId]);

  // Separate featured integrations
  const featuredIntegrations = useMemo(() => {
    return filteredIntegrations.filter((i) => i.isFeatured && i.available);
  }, [filteredIntegrations]);

  // Group ALL integrations by category, sorted: connected first, then alphabetically
  // When a search query is active, preserve Fuse.js relevance order instead of sorting alphabetically
  const integrationsByCategory = useMemo(() => {
    const grouped: Record<string, Integration[]> = {};

    for (const category of availableCategories) {
      const items = filteredIntegrations.filter((i) => i.category === category);
      grouped[category] = searchQuery.trim()
        ? items
        : items.toSorted((a, b) => {
            // Needs-attention (expired, pending) first, then connected
            const orderA =
              INTEGRATION_STATE_ORDER[integrationConnectionState(a.status)];
            const orderB =
              INTEGRATION_STATE_ORDER[integrationConnectionState(b.status)];
            if (orderA !== orderB) return orderA - orderB;
            // Then alphabetically
            return a.name.localeCompare(b.name);
          });
    }

    return grouped;
  }, [filteredIntegrations, availableCategories, searchQuery]);

  // When searching, order categories by which one contains the top-ranked result
  const searchOrderedCategories = useMemo(() => {
    const cats = availableCategories.filter(
      (cat) => cat !== "created_by_you" && cat !== "custom",
    );
    if (!searchQuery.trim()) return cats;

    return cats.toSorted((a, b) => {
      const aIndex = filteredIntegrations.findIndex((i) => i.category === a);
      const bIndex = filteredIntegrations.findIndex((i) => i.category === b);
      if (aIndex !== -1 && bIndex !== -1) {
        return aIndex - bIndex;
      }
      if (aIndex !== -1) return -1;
      if (bIndex !== -1) return 1;
      return 0;
    });
  }, [availableCategories, filteredIntegrations, searchQuery]);

  // For when a specific category is selected
  const integrationsInSelectedCategory = useMemo(() => {
    if (selectedCategory === "created_by_you") {
      return createdByYouIntegrations;
    }
    return filteredIntegrations.filter((i) => i.category === selectedCategory);
  }, [filteredIntegrations, selectedCategory, createdByYouIntegrations]);

  const hasResults =
    selectedCategory === "created_by_you"
      ? createdByYouIntegrations.length > 0
      : filteredIntegrations.length > 0;

  const isAllCategories = selectedCategory === ALL_CATEGORIES;

  return {
    isPending,
    handleConnect,
    availableCategories,
    createdByYouIntegrations,
    featuredIntegrations,
    integrationsByCategory,
    searchOrderedCategories,
    integrationsInSelectedCategory,
    isAllCategories,
    showFilteredEmptyState:
      !isPending && !hasResults && (!!searchQuery || !isAllCategories),
    showCatalogEmptyState:
      !isPending && !hasResults && !searchQuery && integrations.length === 0,
    showFeatured:
      featuredIntegrations.length > 0 && !searchQuery && isAllCategories,
    showCreatedByYou: createdByYouIntegrations.length > 0 && isAllCategories,
  };
}
