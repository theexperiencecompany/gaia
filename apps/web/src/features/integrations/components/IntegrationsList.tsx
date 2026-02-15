import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import type React from "react";
import { useMemo } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrationModalStore } from "@/stores/integrationModalStore";
import { useIntegrationsStore } from "@/stores/integrationsStore";
import { useUserStore } from "@/stores/userStore";
import {
  getCategoryLabel,
  getUniqueCategories,
  sortCategories,
} from "../constants/categories";
import { useIntegrationSearch } from "../hooks/useIntegrationSearch";
import { useIntegrations } from "../hooks/useIntegrations";
import type { Integration } from "../types";
import { CategoryFilter } from "./CategoryFilter";
import { MarketplaceBanner } from "./MarketplaceBanner";

const SuperConnectorRow: React.FC<{
  integration: Integration;
  childIntegrations: Integration[];
  onConnect: (id: string) => void;
  onClick: (id: string) => void;
}> = ({ integration, childIntegrations, onConnect, onClick }) => {
  const connectedCount = childIntegrations.filter(
    (c) => c.status === "connected",
  ).length;
  const totalCount = childIntegrations.length;
  const allConnected = connectedCount === totalCount;

  return (
    <div
      role="button"
      tabIndex={0}
      className="cursor-pointer rounded-2xl border border-zinc-700/50 bg-zinc-800/30 p-4 hover:bg-zinc-800/60 transition-all duration-200"
      onClick={() => onClick(integration.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick(integration.id);
        }
      }}
    >
      <div className="flex items-center gap-4">
        <div className="shrink-0">
          {getToolCategoryIcon(
            integration.id,
            { size: 36, width: 36, height: 36, showBackground: false },
            integration.iconUrl,
          )}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="font-medium">{integration.name}</div>
          <div className="text-sm font-light text-zinc-400">
            {integration.description}
          </div>
        </div>
        <div className="shrink-0">
          {allConnected ? (
            <Chip size="sm" variant="flat" color="success">
              All Connected
            </Chip>
          ) : (
            <Button
              variant="flat"
              color="primary"
              className="text-sm text-primary"
              onPress={() => onConnect(integration.id)}
            >
              {connectedCount > 0
                ? `Connect (${connectedCount}/${totalCount})`
                : "Connect All"}
            </Button>
          )}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 pl-[52px]">
        {childIntegrations.map((child) => (
          <div
            key={child.id}
            className="flex items-center gap-1.5 rounded-lg bg-zinc-800 px-2 py-1"
          >
            {getToolCategoryIcon(
              child.id,
              { size: 16, width: 16, height: 16, showBackground: false },
              child.iconUrl,
            )}
            <span className="text-xs text-zinc-300">{child.name}</span>
            {child.status === "connected" && (
              <div
                className="h-1.5 w-1.5 rounded-full bg-green-500"
                role="img"
                aria-label="Connected"
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

const IntegrationRow: React.FC<{
  integration: Integration;
  onConnect: (id: string) => void;
  onClick: (id: string) => void;
}> = ({ integration, onConnect, onClick }) => {
  const isConnected = integration.status === "connected";
  // Custom integrations are always available, platform integrations use available field
  const isAvailable = integration.source === "custom" || integration.available;

  const handleClick = () => {
    onClick(integration.id);
  };

  return (
    <div
      className="flex min-h-16 cursor-pointer items-center gap-4 overflow-hidden rounded-2xl bg-zinc-800/0 px-4 py-3 hover:bg-zinc-800 transition-all duration-200"
      onClick={handleClick}
    >
      <div className="shrink-0">
        {getToolCategoryIcon(
          integration.id,
          {
            size: 32,
            width: 32,
            height: 32,
            showBackground: false,
          },
          integration.iconUrl,
        )}
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
  const openModal = useIntegrationModalStore((state) => state.openModal);
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
  const currentUserId = useUserStore((state) => state.userId);

  const { filteredIntegrations } = useIntegrationSearch(integrations);

  // Separate super-connectors from regular integrations
  const superConnectors = useMemo(() => {
    return filteredIntegrations.filter(
      (i) => i.isSpecial && i.includedIntegrations?.length,
    );
  }, [filteredIntegrations]);

  const superConnectorChildIds = useMemo(() => {
    return new Set(
      superConnectors.flatMap((sc) => sc.includedIntegrations || []),
    );
  }, [superConnectors]);

  // Regular integrations (exclude super-connectors themselves)
  const regularIntegrations = useMemo(() => {
    return filteredIntegrations.filter((i) => !i.isSpecial);
  }, [filteredIntegrations]);

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

  // Separate featured integrations (exclude children of super-connectors)
  const featuredIntegrations = useMemo(() => {
    return regularIntegrations.filter(
      (i) =>
        i.isFeatured &&
        i.available &&
        (!superConnectorChildIds.has(i.id) || searchQuery),
    );
  }, [regularIntegrations, superConnectorChildIds, searchQuery]);

  // Group ALL integrations by category, sorted: connected first, then alphabetically
  const integrationsByCategory = useMemo(() => {
    const grouped: Record<string, Integration[]> = {};

    for (const category of availableCategories) {
      grouped[category] = regularIntegrations
        .filter(
          (i) =>
            i.category === category &&
            (!superConnectorChildIds.has(i.id) || searchQuery),
        )
        .sort((a, b) => {
          // Connected first
          if (a.status === "connected" && b.status !== "connected") return -1;
          if (a.status !== "connected" && b.status === "connected") return 1;
          // Then alphabetically
          return a.name.localeCompare(b.name);
        });
    }

    return grouped;
  }, [regularIntegrations, availableCategories, superConnectorChildIds, searchQuery]);

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

  return (
    <div>
      {/* Marketplace Banner */}
      <div className="my-8">
        <MarketplaceBanner onCreateCustomIntegration={openModal} />
      </div>

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

      {/* Super-Connectors */}
      {superConnectors.length > 0 &&
        !searchQuery &&
        selectedCategory === "all" && (
          <div className="mb-8">
            <div className="mb-4 flex items-center gap-3 pl-4">
              <h2 className="text-base font-semibold">Bundles</h2>
            </div>
            <div className="flex flex-col gap-3">
              {superConnectors.map((sc) => (
                <SuperConnectorRow
                  key={sc.id}
                  integration={sc}
                  childIntegrations={integrations.filter((i) =>
                    sc.includedIntegrations?.includes(i.id),
                  )}
                  onConnect={handleConnect}
                  onClick={(id) => onIntegrationClick?.(id)}
                />
              ))}
            </div>
          </div>
        )}

      {/* Featured Section */}
      {featuredIntegrations.length > 0 &&
        !searchQuery &&
        selectedCategory === "all" && (
          <IntegrationSection
            title="Featured"
            integrations={featuredIntegrations}
            chipColor="primary"
            onConnect={handleConnect}
            onIntegrationClick={onIntegrationClick}
          />
        )}

      {createdByYouIntegrations.length > 0 &&
        !searchQuery &&
        selectedCategory === "all" && (
          <IntegrationSection
            title="Created by You"
            integrations={createdByYouIntegrations}
            onConnect={handleConnect}
            onIntegrationClick={onIntegrationClick}
          />
        )}

      {selectedCategory === "all" ? (
        // Exclude "created_by_you" virtual category (shown above) and "custom" category.
        // Custom integrations with createdBy set are shown in "Created by You" section.
        // Note: This assumes all user-created integrations have createdBy property set.
        // If createdBy is missing, the integration would appear in duplicate sections.
        availableCategories
          .filter((cat) => cat !== "created_by_you" && cat !== "custom")
          .map((category) => {
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
