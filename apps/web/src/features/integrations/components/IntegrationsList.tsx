import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import type React from "react";
import { useIntegrationModalActions } from "@/stores/uiStore";
import { getCategoryLabel } from "../constants/categories";
import { useIntegrationsList } from "../hooks/useIntegrationsList";
import { CategoryFilter } from "./CategoryFilter";
import { IntegrationSection } from "./IntegrationSection";
import { MarketplaceBanner } from "./MarketplaceBanner";

// Distinct keys for the initial catalog placeholders (also serve as React keys).
const INTEGRATION_SKELETON_KEYS = [
  "int-a",
  "int-b",
  "int-c",
  "int-d",
  "int-e",
  "int-f",
];

interface NoIntegrationsFoundProps {
  searchQuery: string;
  selectedCategory: string;
  clearFilters: () => void;
}

const NoIntegrationsFound: React.FC<NoIntegrationsFoundProps> = ({
  searchQuery,
  selectedCategory,
  clearFilters,
}) => (
  <div className="py-16 text-center space-y-2">
    <p className="text-sm text-zinc-400">
      {searchQuery
        ? `No integrations found for "${searchQuery}"`
        : `No ${getCategoryLabel(selectedCategory).toLowerCase()} integrations found`}
    </p>
    <Button onPress={clearFilters} variant="light" color="primary" size="sm">
      Clear filters
    </Button>
  </div>
);

interface IntegrationsListProps {
  onIntegrationClick?: (integrationId: string) => void;
  searchQuery: string;
  selectedCategory: string;
  setSelectedCategory: (category: string) => void;
  clearFilters: () => void;
}

export const IntegrationsList: React.FC<IntegrationsListProps> = ({
  onIntegrationClick,
  searchQuery,
  selectedCategory,
  setSelectedCategory,
  clearFilters,
}) => {
  const { openIntegrationModal } = useIntegrationModalActions();
  const {
    isPending,
    handleConnect,
    availableCategories,
    createdByYouIntegrations,
    featuredIntegrations,
    integrationsByCategory,
    searchOrderedCategories,
    integrationsInSelectedCategory,
    isAllCategories,
    showFilteredEmptyState,
    showCatalogEmptyState,
    showFeatured,
    showCreatedByYou,
  } = useIntegrationsList({
    searchQuery,
    selectedCategory,
    onIntegrationClick,
  });

  return (
    <div>
      {/* Marketplace Banner */}
      <div className="my-8">
        <MarketplaceBanner onCreateCustomIntegration={openIntegrationModal} />
      </div>

      <div className="mb-6">
        <CategoryFilter
          categories={availableCategories}
          selectedCategory={selectedCategory}
          onCategoryChange={setSelectedCategory}
        />
      </div>

      {/* The catalog is still loading — placeholders, never the empty state. */}
      {isPending && (
        <div className="flex flex-col gap-2">
          {INTEGRATION_SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-16 w-full rounded-2xl" />
          ))}
        </div>
      )}

      {/* No Results State */}
      {showFilteredEmptyState && (
        <NoIntegrationsFound
          searchQuery={searchQuery}
          selectedCategory={selectedCategory}
          clearFilters={clearFilters}
        />
      )}

      {showCatalogEmptyState && (
        <div className="py-16 text-center">
          <p className="text-sm text-zinc-400">No integrations available</p>
          <p className="mt-1 text-xs text-zinc-500">
            Check back later for new integrations
          </p>
        </div>
      )}

      {/* Featured Section */}
      {showFeatured && (
        <IntegrationSection
          title="Featured"
          integrations={featuredIntegrations}
          chipColor="primary"
          onConnect={handleConnect}
          onIntegrationClick={onIntegrationClick}
        />
      )}

      {showCreatedByYou && (
        <IntegrationSection
          title="Created by You"
          integrations={createdByYouIntegrations}
          onConnect={handleConnect}
          onIntegrationClick={onIntegrationClick}
        />
      )}

      {isAllCategories ? (
        // Exclude "created_by_you" virtual category (shown above) and "custom" category.
        // Custom integrations with createdBy set are shown in "Created by You" section.
        // Note: This assumes all user-created integrations have createdBy property set.
        // If createdBy is missing, the integration would appear in duplicate sections.
        searchOrderedCategories.map((category) => (
          <IntegrationSection
            key={category}
            title={getCategoryLabel(category)}
            integrations={integrationsByCategory[category] ?? []}
            onConnect={handleConnect}
            onIntegrationClick={onIntegrationClick}
          />
        ))
      ) : (
        <IntegrationSection
          title={getCategoryLabel(selectedCategory)}
          integrations={integrationsInSelectedCategory}
          onConnect={handleConnect}
          onIntegrationClick={onIntegrationClick}
        />
      )}
    </div>
  );
};
