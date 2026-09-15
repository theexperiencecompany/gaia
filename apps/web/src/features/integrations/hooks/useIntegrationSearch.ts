"use client";

import Fuse from "fuse.js";
import { useMemo } from "react";

import { ALL_CATEGORIES } from "../constants/categories";
import type { Integration } from "../types";

export function useIntegrationSearch(
  integrations: Integration[],
  searchQuery: string,
  selectedCategory: string,
) {
  const fuse = useMemo(
    () =>
      new Fuse(integrations, {
        keys: [
          { name: "name", weight: 2 },
          { name: "description", weight: 1 },
          { name: "id", weight: 0.5 },
          { name: "category", weight: 0.3 },
        ],
        threshold: 0.4,
        ignoreLocation: true,
        useExtendedSearch: false,
        minMatchCharLength: 1,
      }),
    [integrations],
  );

  const filteredIntegrations = useMemo(() => {
    let results = integrations;

    if (selectedCategory !== ALL_CATEGORIES) {
      if (selectedCategory === "created_by_you") {
        results = results.filter((i) => i.createdBy);
      } else {
        results = results.filter((i) => i.category === selectedCategory);
      }
    }

    if (searchQuery.trim()) {
      const fuseResults = fuse.search(searchQuery).map((r) => r.item);
      if (fuseResults.length === 0) {
        const query = searchQuery.toLowerCase();
        results = results.filter(
          (i) =>
            i.name.toLowerCase().includes(query) ||
            i.description?.toLowerCase().includes(query) ||
            i.id.toLowerCase().includes(query),
        );
      } else {
        results = fuseResults;
      }
    }

    return results;
  }, [searchQuery, selectedCategory, fuse, integrations]);

  return { filteredIntegrations };
}
