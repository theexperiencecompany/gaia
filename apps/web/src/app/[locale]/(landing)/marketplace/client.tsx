"use client";

import { Pagination } from "@heroui/pagination";
import Image from "next/image";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import { IntegrationsFilters } from "@/features/integrations/components/IntegrationsFilters";
import {
  PublicIntegrationCard,
  PublicIntegrationCardSkeletonGrid,
} from "@/features/integrations/components/PublicIntegrationCard";
import type { CommunityIntegration } from "@/features/integrations/types";
import FinalSection from "@/features/landing/components/sections/FinalSection";

const ITEMS_PER_PAGE = 18;

export function IntegrationsPageClient() {
  const searchParams = useSearchParams();
  const [integrations, setIntegrations] = useState<CommunityIntegration[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isFiltering, setIsFiltering] = useState(false);
  const [total, setTotal] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [filters, setFilters] = useState<{
    search: string;
    category: string;
    sort: "popular" | "recent" | "name";
  }>({
    search: searchParams.get("search") || "",
    category: searchParams.get("category") || "all",
    sort: "popular",
  });
  const isInitialMount = useRef(true);
  const hasRefreshed = useRef(false);

  // Native integrations state (fetched once, filtered client-side)
  const [nativeIntegrations, setNativeIntegrations] = useState<
    CommunityIntegration[]
  >([]);
  const [, setNativeLoading] = useState(false);
  const nativeFetched = useRef(false);

  const totalPages = useMemo(() => Math.ceil(total / ITEMS_PER_PAGE), [total]);

  const loadIntegrations = useCallback(
    async (page: number, showFilteringSkeleton = false) => {
      setIsLoading(true);
      if (showFilteringSkeleton) {
        setIsFiltering(true);
      }
      try {
        const response = await integrationsApi.getCommunityIntegrations({
          sort: filters.sort,
          category: filters.category === "all" ? undefined : filters.category,
          search: filters.search || undefined,
          limit: ITEMS_PER_PAGE,
          offset: (page - 1) * ITEMS_PER_PAGE,
        });

        setIntegrations(response.integrations);
        setTotal(response.total);
      } catch (error) {
        console.error("Failed to load integrations:", error);
      } finally {
        setIsLoading(false);
        setIsFiltering(false);
      }
    },
    [filters],
  );

  const loadNativeIntegrations = useCallback(async () => {
    if (nativeFetched.current) return;
    nativeFetched.current = true;
    setNativeLoading(true);
    try {
      const result = await integrationsApi.getNativeIntegrations();
      setNativeIntegrations(result);
    } catch (error) {
      console.error("Failed to load native integrations:", error);
      nativeFetched.current = false;
    } finally {
      setNativeLoading(false);
    }
  }, []);

  // Load native integrations on mount
  useEffect(() => {
    loadNativeIntegrations();
  }, [loadNativeIntegrations]);

  // Client-side filtering for native integrations
  const filteredNativeIntegrations = useMemo(() => {
    return nativeIntegrations.filter((i) => {
      const matchesCategory =
        filters.category === "all" || i.category === filters.category;
      const q = filters.search.toLowerCase();
      const matchesSearch =
        !filters.search ||
        i.name.toLowerCase().includes(q) ||
        i.description.toLowerCase().includes(q);
      return matchesCategory && matchesSearch;
    });
  }, [filters.category, filters.search, nativeIntegrations]);

  // Handle ?refresh=true query parameter
  useEffect(() => {
    if (typeof window === "undefined" || hasRefreshed.current) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("refresh") === "true") {
      hasRefreshed.current = true;
      loadIntegrations(1, false);
      window.history.replaceState({}, "", "/marketplace");
    }
  }, [loadIntegrations]);

  // Load when filters change - reset to page 1
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      loadIntegrations(1, false);
    } else {
      setCurrentPage(1);
      loadIntegrations(1, true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.search, filters.category, filters.sort]);

  // Handle page change
  const handlePageChange = (page: number) => {
    setCurrentPage(page);
    loadIntegrations(page, false);
    window.scrollTo({ top: 400, behavior: "smooth" });
  };

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

  const showSkeletons = isLoading && (integrations.length === 0 || isFiltering);

  const displayLoading = showSkeletons;
  const displayTotal = filteredNativeIntegrations.length + total;

  return (
    <div className="min-h-screen pt-32 pb-16">
      <div className="absolute inset-0 top-0 z-0 h-[70vh] w-full">
        <Image
          src={"/images/wallpapers/library.webp"}
          alt="GAIA Use-Cases Wallpaper"
          sizes="100vw"
          priority
          fill
          className="aspect-video object-cover object-center opacity-80"
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[40vh] bg-linear-to-t from-background to-transparent" />
      </div>

      <div className="mx-auto max-w-7xl px-6 z-1 relative mt-40">
        <div className="mb-12">
          <h1 className="mb-4 font-serif text-5xl md:text-7xl font-normal text-foreground">
            Integration Marketplace
          </h1>
          <p className="text-lg text-foreground-500 font-light max-w-2xl">
            Discover and automate your favorite tools with AI. Browse
            community-built MCP integrations to connect Gmail, Slack, Notion,
            GitHub, and 50+ services to your AI assistant.
          </p>
        </div>

        <IntegrationsFilters
          onFilterChange={handleFilterChange}
          initialFilters={filters}
        />

        {displayLoading && (
          <p className="mb-6 text-sm text-zinc-500">Loading...</p>
        )}
        {!displayLoading && (
          <p className="mb-6 text-sm text-zinc-500">
            {displayTotal} integration{displayTotal !== 1 ? "s" : ""} found
          </p>
        )}

        {displayLoading ? (
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            <PublicIntegrationCardSkeletonGrid count={6} />
          </div>
        ) : filteredNativeIntegrations.length === 0 &&
          integrations.length === 0 ? (
          <div className="py-20 text-center">
            <p className="text-zinc-400">No integrations found</p>
            <p className="mt-2 text-sm text-zinc-500">
              Try adjusting your search or filters
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
              {filteredNativeIntegrations.map((integration) => (
                <PublicIntegrationCard
                  key={integration.integrationId}
                  integration={integration}
                />
              ))}
              {integrations.map((integration) => (
                <PublicIntegrationCard
                  key={integration.integrationId}
                  integration={integration}
                />
              ))}
            </div>

            {/* Pagination — community only */}
            {totalPages > 1 && (
              <div className="mt-12 flex justify-center">
                <Pagination
                  total={totalPages}
                  page={currentPage}
                  onChange={handlePageChange}
                  showControls
                  variant="faded"
                  classNames={{
                    base: "cursor-pointer!",
                  }}
                />
              </div>
            )}
          </>
        )}
      </div>

      <FinalSection />
    </div>
  );
}
