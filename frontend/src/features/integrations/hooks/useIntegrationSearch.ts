import { useMemo, useState } from "react";

import { Integration } from "../types";

export const useIntegrationSearch = (integrations: Integration[]) => {
  const [searchQuery, setSearchQuery] = useState("");

  const filteredIntegrations = useMemo(() => {
    if (!searchQuery.trim()) {
      return integrations;
    }

    const query = searchQuery.toLowerCase();
    return integrations.filter(
      (integration) =>
        integration.name.toLowerCase().includes(query) ||
        integration.description.toLowerCase().includes(query),
    );
  }, [integrations, searchQuery]);

  const clearSearch = () => setSearchQuery("");

  return {
    searchQuery,
    setSearchQuery,
    clearSearch,
    filteredIntegrations,
  };
};
