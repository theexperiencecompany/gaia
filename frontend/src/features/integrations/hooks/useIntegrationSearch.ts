import Fuse from "fuse.js";
import { useMemo, useState } from "react";
import type { Integration } from "../types";

export function useIntegrationSearch(integrations: Integration[]) {
  const [searchQuery, setSearchQuery] = useState("");

  const fuse = useMemo(() => {
    return new Fuse(integrations, {
      keys: ["name", "description", "id"],
      threshold: 0.3,
    });
  }, [integrations]);

  const filteredIntegrations = useMemo(() => {
    if (!searchQuery.trim()) return integrations;
    return fuse.search(searchQuery).map((r) => r.item);
  }, [searchQuery, fuse, integrations]);

  const clearSearch = () => setSearchQuery("");

  return {
    searchQuery,
    setSearchQuery,
    clearSearch,
    filteredIntegrations,
  };
}
