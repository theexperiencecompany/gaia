import { useDeferredValue, useMemo, useState } from "react";

import { ALL } from "../explore/useExplore";
import { type App, categoryLabel, isByGaia } from "./appModel";

function matches(app: App, query: string): boolean {
  return `${app.name} ${app.description} ${categoryLabel(app.category)} ${app.creator?.name ?? ""}`
    .toLowerCase()
    .includes(query);
}

/** The marketplace's search and category, and the two shelves they leave: GAIA's apps, then the community's. */
export function useMarketplace(apps: App[]) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState(ALL);
  const needle = useDeferredValue(query.trim().toLowerCase());

  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const app of apps) {
      counts.set(app.category, (counts.get(app.category) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([id]) => id);
  }, [apps]);

  const results = useMemo(
    () =>
      apps.filter(
        (app) =>
          (category === ALL || app.category === category) &&
          (!needle || matches(app, needle)),
      ),
    [apps, category, needle],
  );

  return {
    query,
    setQuery,
    category,
    setCategory,
    categories,
    gaia: results.filter(isByGaia),
    community: results.filter((app) => !isByGaia(app)),
    isEmpty: results.length === 0,
    reset: () => {
      setQuery("");
      setCategory(ALL);
    },
  };
}
