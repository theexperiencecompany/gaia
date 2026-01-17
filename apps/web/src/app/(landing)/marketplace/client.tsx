"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { useCallback, useEffect, useState } from "react";

import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import { IntegrationsFilters } from "@/features/integrations/components/IntegrationsFilters";
import { PublicIntegrationCard } from "@/features/integrations/components/PublicIntegrationCard";
import type { CommunityIntegration } from "@/features/integrations/types";

export function IntegrationsPageClient() {
  const [integrations, setIntegrations] = useState<CommunityIntegration[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState<{
    search: string;
    category: string;
    sort: "popular" | "recent" | "name";
  }>({
    search: "",
    category: "all",
    sort: "popular",
  });

  const loadIntegrations = useCallback(
    async (reset = false) => {
      setIsLoading(true);
      try {
        const response = await integrationsApi.getCommunityIntegrations({
          sort: filters.sort,
          category: filters.category === "all" ? undefined : filters.category,
          search: filters.search || undefined,
          limit: 20,
          offset: reset ? 0 : integrations.length,
        });

        if (reset) {
          setIntegrations(response.integrations);
        } else {
          setIntegrations((prev) => [...prev, ...response.integrations]);
        }
        setHasMore(response.hasMore);
        setTotal(response.total);
      } catch (error) {
        console.error("Failed to load integrations:", error);
      } finally {
        setIsLoading(false);
      }
    },
    [filters, integrations.length],
  );

  useEffect(() => {
    loadIntegrations(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.search, filters.category, filters.sort]);

  const handleFilterChange = (newFilters: {
    search?: string;
    category?: string;
    sort?: string;
  }) => {
    setFilters((prev) => ({
      ...prev,
      ...newFilters,
      sort: (newFilters.sort as "popular" | "recent" | "name") || prev.sort,
    }));
  };

  return (
    <div className="min-h-screen pt-32 pb-16">
      <div className="mx-auto max-w-7xl px-6">
        {/* Header */}
        <div className="mb-12">
          <h1 className="mb-4 font-serif text-5xl md:text-6xl text-white">
            Integration Marketplace
          </h1>
          <p className="text-lg text-zinc-400 max-w-2xl">
            Discover MCP integrations built by the community. Clone them to your
            workspace and connect AI tools to your favorite services.
          </p>
        </div>

        {/* Filters */}
        <IntegrationsFilters
          onFilterChange={handleFilterChange}
          initialFilters={filters}
        />

        {/* Results count */}
        {!isLoading && (
          <p className="mb-6 text-sm text-zinc-500">
            {total} integration{total !== 1 ? "s" : ""} found
          </p>
        )}

        {/* Grid */}
        {isLoading && integrations.length === 0 ? (
          <div className="flex justify-center py-20">
            <Spinner size="lg" />
          </div>
        ) : integrations.length === 0 ? (
          <div className="py-20 text-center">
            <p className="text-zinc-400">No integrations found</p>
            <p className="mt-2 text-sm text-zinc-500">
              Try adjusting your search or filters
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
              {integrations.map((integration) => (
                <PublicIntegrationCard
                  key={integration.integrationId}
                  integration={integration}
                />
              ))}
            </div>

            {/* Load more */}
            {hasMore && (
              <div className="mt-8 flex justify-center">
                <Button
                  variant="flat"
                  onPress={() => loadIntegrations(false)}
                  isLoading={isLoading}
                >
                  Load More
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
