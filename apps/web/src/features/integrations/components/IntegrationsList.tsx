import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import type React from "react";
import { useMemo } from "react";
import { Separator } from "@/components";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrationsStore } from "@/stores/integrationsStore";
import {
  getCategoryLabel,
  getUniqueCategories,
  sortCategories,
} from "../constants/categories";
import { useIntegrationSearch } from "../hooks/useIntegrationSearch";
import { useIntegrations } from "../hooks/useIntegrations";
import type { Integration } from "../types";
import { CategoryFilter } from "./CategoryFilter";

const IntegrationRow: React.FC<{
  integration: Integration;
  onConnect: (id: string) => void;
  onClick: (id: string) => void;
}> = ({ integration, onConnect, onClick }) => {
  const isConnected = integration.status === "connected";
  const isAvailable = !!integration.loginEndpoint;

  const handleClick = () => {
    onClick(integration.id);
  };

  return (
    <div
      className="flex min-h-16 cursor-pointer items-center gap-4 overflow-hidden rounded-2xl bg-zinc-800/0 px-4 py-3 hover:bg-zinc-800 transition-all duration-200"
      onClick={handleClick}
    >
      <div className="shrink-0">
        {getToolCategoryIcon(integration.id, {
          size: 32,
          width: 32,
          height: 32,
          showBackground: false,
        })}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="font-medium">{integration.name}</div>
        <div className="truncate text-sm font-light text-zinc-400">
          {integration.description}
        </div>
      </div>

      <div className="shrink-0">
        {isConnected && (
          <Chip size="sm" variant="flat" color="success">
            Connected
          </Chip>
        )}

        {isAvailable && !isConnected && (
          <Button
            variant="flat"
            color="primary"
            className="text-sm text-primary"
            onPress={() => {
              onConnect(integration.id);
            }}
          >
            Connect
          </Button>
        )}

        {!isAvailable && (
          <Chip size="sm" variant="flat" color="default" className="text-xs">
            Soon
          </Chip>
        )}
      </div>
    </div>
  );
};

interface IntegrationSectionProps {
  title: string;
  integrations: Integration[];
  chipColor?: "primary" | "default";
  onConnect: (id: string) => void;
  onIntegrationClick?: (id: string) => void;
}

const IntegrationSection: React.FC<IntegrationSectionProps> = ({
  title,
  integrations,
  chipColor = "default",
  onConnect,
  onIntegrationClick,
}) => {
  if (integrations.length === 0) return null;

  return (
    <div className="mb-8">
      <div className="mb-4 flex items-center gap-3 pl-4">
        <h2 className="text-base font-semibold">{title}</h2>
        <Chip size="sm" variant="flat" color={chipColor}>
          {integrations.length}
        </Chip>
      </div>
      <div className="flex flex-col gap-2">
        {integrations.map((integration) => (
          <IntegrationRow
            key={integration.id}
            integration={integration}
            onConnect={onConnect}
            onClick={(id) => onIntegrationClick?.(id)}
          />
        ))}
      </div>
    </div>
  );
};

export const IntegrationsList: React.FC<{
  onIntegrationClick?: (integrationId: string) => void;
}> = ({ onIntegrationClick }) => {
  const { integrations, connectIntegration } = useIntegrations();

  // Get state from store
  const searchQuery = useIntegrationsStore((state) => state.searchQuery);
  const selectedCategory = useIntegrationsStore(
    (state) => state.selectedCategory,
  );
  const setSelectedCategory = useIntegrationsStore(
    (state) => state.setSelectedCategory,
  );
  const clearFilters = useIntegrationsStore((state) => state.clearFilters);

  const { filteredIntegrations } = useIntegrationSearch(integrations);

  const handleConnect = async (integrationId: string) => {
    try {
      await connectIntegration(integrationId);
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  // Derive categories from backend integrations data
  const availableCategories = useMemo(() => {
    const uniqueCategories = getUniqueCategories(integrations);
    return sortCategories(uniqueCategories);
  }, [integrations]);

  // Separate featured integrations
  const featuredIntegrations = useMemo(() => {
    return filteredIntegrations.filter((i) => i.isFeatured && i.loginEndpoint);
  }, [filteredIntegrations]);

  // Group ALL integrations by category (featured will appear in both Featured and their category)
  const integrationsByCategory = useMemo(() => {
    const grouped: Record<string, Integration[]> = {};

    for (const category of availableCategories) {
      grouped[category] = filteredIntegrations.filter(
        (i) => i.category === category,
      );
    }

    return grouped;
  }, [filteredIntegrations, availableCategories]);

  // For when a specific category is selected
  const integrationsInSelectedCategory = useMemo(() => {
    return filteredIntegrations.filter((i) => i.category === selectedCategory);
  }, [filteredIntegrations, selectedCategory]);

  const hasResults = filteredIntegrations.length > 0;

  return (
    <div>
      {/* Category Filter - categories derived from backend data */}
      <div className="mb-6">
        <CategoryFilter
          categories={availableCategories}
          selectedCategory={selectedCategory}
          onCategoryChange={setSelectedCategory}
        />
      </div>

      {/* No Results State */}
      {!hasResults && (searchQuery || selectedCategory !== "all") && (
        <div className="py-16 text-center space-y-2">
          <p className="text-sm text-zinc-400">
            {searchQuery
              ? `No integrations found for "${searchQuery}"`
              : `No ${getCategoryLabel(selectedCategory).toLowerCase()} integrations found`}
          </p>
          <Button
            onPress={clearFilters}
            variant="light"
            color="primary"
            size="sm"
          >
            Clear filters
          </Button>
        </div>
      )}

      {!hasResults && !searchQuery && integrations.length === 0 && (
        <div className="py-16 text-center">
          <p className="text-sm text-zinc-400">No integrations available</p>
          <p className="mt-1 text-xs text-zinc-500">
            Check back later for new integrations
          </p>
        </div>
      )}

      {/* Featured Section */}
      {featuredIntegrations.length > 0 && (
        <>
          <IntegrationSection
            title="Featured"
            integrations={featuredIntegrations}
            chipColor="primary"
            onConnect={handleConnect}
            onIntegrationClick={onIntegrationClick}
          />
          <Separator className="border-zinc-800 border-t-1 mb-8" />
        </>
      )}

      {/* Category Sections */}
      {selectedCategory === "all" ? (
        // When "All" is selected, show integrations grouped by category
        availableCategories.map((category) => {
          const categoryIntegrations = integrationsByCategory[category];
          if (!categoryIntegrations || categoryIntegrations.length === 0)
            return null;

          return (
            <IntegrationSection
              key={category}
              title={getCategoryLabel(category)}
              integrations={categoryIntegrations}
              onConnect={handleConnect}
              onIntegrationClick={onIntegrationClick}
            />
          );
        })
      ) : (
        // When a specific category is selected, show all integrations in that category
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
