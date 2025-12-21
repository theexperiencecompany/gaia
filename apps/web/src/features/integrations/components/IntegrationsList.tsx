import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import type React from "react";
import { useMemo, useState } from "react";
import { Separator } from "@/components";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  CATEGORY_DISPLAY_ORDER,
  getCategoryLabel,
} from "../constants/categories";
import { useIntegrationSearch } from "../hooks/useIntegrationSearch";
import { useIntegrations } from "../hooks/useIntegrations";
import type { Integration } from "../types";
import { CategoryFilter } from "./CategoryFilter";
import { IntegrationsSearchInput } from "./IntegrationsSearchInput";
import { MCPIntegrationModal } from "./MCPIntegrationModal";

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
  const [isMCPModalOpen, setIsMCPModalOpen] = useState(false);

  const {
    searchQuery,
    setSearchQuery,
    clearSearch,
    selectedCategory,
    setSelectedCategory,
    filteredIntegrations,
  } = useIntegrationSearch(integrations);

  const handleConnect = async (integrationId: string) => {
    try {
      await connectIntegration(integrationId);
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  // Separate featured integrations (only for "all" category or when featured are in the selected category)
  const featuredIntegrations = useMemo(() => {
    return filteredIntegrations.filter((i) => i.isFeatured && i.loginEndpoint);
  }, [filteredIntegrations]);

  // Non-featured integrations
  const nonFeaturedIntegrations = useMemo(() => {
    return filteredIntegrations.filter((i) => !i.isFeatured);
  }, [filteredIntegrations]);

  // Group non-featured integrations by category
  const integrationsByCategory = useMemo(() => {
    const grouped: Record<string, Integration[]> = {};

    for (const category of CATEGORY_DISPLAY_ORDER) {
      grouped[category] = nonFeaturedIntegrations.filter(
        (i) => i.category === category,
      );
    }

    return grouped;
  }, [nonFeaturedIntegrations]);

  const hasResults = filteredIntegrations.length > 0;

  return (
    <div>
      {/* Search and Category Filter */}
      <div className="mb-6 space-y-4">
        <div className="flex justify-between items-center">
          <CategoryFilter
            selectedCategory={selectedCategory}
            onCategoryChange={setSelectedCategory}
          />
          <IntegrationsSearchInput
            value={searchQuery}
            onChange={setSearchQuery}
            onClear={clearSearch}
          />
        </div>
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
            onPress={() => {
              clearSearch();
              setSelectedCategory("all");
            }}
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
        CATEGORY_DISPLAY_ORDER.map((category) => {
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
        // When a specific category is selected, show flat list (non-featured only)
        <IntegrationSection
          title={getCategoryLabel(selectedCategory)}
          integrations={nonFeaturedIntegrations}
          onConnect={handleConnect}
          onIntegrationClick={onIntegrationClick}
        />
      )}

      <MCPIntegrationModal
        isOpen={isMCPModalOpen}
        onClose={() => setIsMCPModalOpen(false)}
      />
    </div>
  );
};
