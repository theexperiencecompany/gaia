"use client";

import Fuse from "fuse.js";
import { useMemo } from "react";
import { useIntegrationsStore } from "@/stores/integrationsStore";
import type { Integration } from "../types";

export function useIntegrationSearch(integrations: Integration[]) {
  const searchQuery = useIntegrationsStore((state) => state.searchQuery);
  const selectedCategory = useIntegrationsStore(
    (state) => state.selectedCategory,
  );

  const fuse = useMemo(() => {
    return new Fuse(integrations, {
      keys: ["name", "description", "id"],
      threshold: 0.3,
    });
  }, [integrations]);

  const filteredIntegrations = useMemo(() => {
    let results = integrations;

    // Apply search filter
    if (searchQuery.trim()) {
      results = fuse.search(searchQuery).map((r) => r.item);
    }

    // Apply category filter
    if (selectedCategory !== "all") {
      if (selectedCategory === "created_by_you") {
        results = results.filter((i) => i.createdBy);
      } else {
        results = results.filter((i) => i.category === selectedCategory);
      }
    }

    return results;
  }, [searchQuery, selectedCategory, fuse, integrations]);

  return {
    filteredIntegrations,
  };
}
