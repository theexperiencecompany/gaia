"use client";

import Fuse from "fuse.js";
import { useMemo, useState } from "react";
import type { IntegrationCategoryId } from "../constants/categories";
import type { Integration } from "../types";

export function useIntegrationSearch(integrations: Integration[]) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] =
    useState<IntegrationCategoryId>("all");

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
      results = results.filter((i) => i.category === selectedCategory);
    }

    return results;
  }, [searchQuery, selectedCategory, fuse, integrations]);

  const clearSearch = () => setSearchQuery("");
  const clearCategory = () => setSelectedCategory("all");

  return {
    searchQuery,
    setSearchQuery,
    clearSearch,
    selectedCategory,
    setSelectedCategory,
    clearCategory,
    filteredIntegrations,
  };
}
