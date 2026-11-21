import { useDeferredValue, useMemo, useState } from "react";
import { appName } from "../marketplace/appModel";
import { type Template, type TemplateData, toTemplate } from "./templateModel";

export const ALL = "all";
/** The shelf for templates their publisher filed under no category. */
export const OTHER = "Other";

export interface Shelf {
  category: string;
  templates: Template[];
}

export interface ExploreFilters {
  query: string;
  category: string;
  app: string;
}

function byFeaturedFirst(a: Template, b: Template): number {
  return Number(b.data.featured) - Number(a.data.featured);
}

function haystack(template: Template): string {
  const { title, summary, body, categories, integration_ids } = template.data;
  return [title, summary, body, ...categories, ...integration_ids.map(appName)]
    .join(" ")
    .toLowerCase();
}

/** Categories by how many templates they hold, so the busiest come first. */
function categoriesOf(templates: Template[]): string[] {
  const counts = new Map<string, number>();
  for (const template of templates) {
    for (const category of template.data.categories) {
      counts.set(category, (counts.get(category) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([category]) => category);
}

/** Every app any template needs, most-used first. */
function appsOf(templates: Template[]): string[] {
  const counts = new Map<string, number>();
  for (const template of templates) {
    for (const app of template.data.integration_ids) {
      counts.set(app, (counts.get(app) ?? 0) + 1);
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([app]) => app);
}

/** The Explore list's filters and what they leave, shelved by category when nothing narrows it. */
export function useExplore(
  data: TemplateData[],
  initial: Partial<ExploreFilters> = {},
) {
  const templates = useMemo(
    () => data.map(toTemplate).sort(byFeaturedFirst),
    [data],
  );
  const categories = useMemo(() => categoriesOf(templates), [templates]);
  const apps = useMemo(() => appsOf(templates), [templates]);
  const [filters, setFilters] = useState<ExploreFilters>({
    query: "",
    category: ALL,
    app: ALL,
    ...initial,
  });
  const query = useDeferredValue(filters.query.trim().toLowerCase());

  const results = useMemo(
    () =>
      templates.filter(
        (template) =>
          (filters.category === ALL ||
            template.data.categories.includes(filters.category)) &&
          (filters.app === ALL ||
            template.data.integration_ids.includes(filters.app)) &&
          (!query || haystack(template).includes(query)),
      ),
    [templates, filters.category, filters.app, query],
  );

  const isNarrowed =
    filters.category !== ALL || filters.app !== ALL || query !== "";

  const shelves = useMemo<Shelf[]>(() => {
    if (isNarrowed) return [];
    const shelved = categories.map((category) => ({
      category,
      templates: results.filter((template) =>
        template.data.categories.includes(category),
      ),
    }));
    const unfiled = results.filter(
      (template) => template.data.categories.length === 0,
    );
    return unfiled.length > 0
      ? [...shelved, { category: OTHER, templates: unfiled }]
      : shelved;
  }, [isNarrowed, categories, results]);

  return {
    filters,
    setFilters: (patch: Partial<ExploreFilters>) =>
      setFilters((current) => ({ ...current, ...patch })),
    reset: () => setFilters({ query: "", category: ALL, app: ALL }),
    categories,
    apps,
    results,
    shelves,
    isNarrowed,
  };
}

export type ExploreState = ReturnType<typeof useExplore>;
