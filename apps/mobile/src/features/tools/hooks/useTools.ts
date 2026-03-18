import { useCallback, useEffect, useState } from "react";
import type { Tool } from "../api/tools-api";
import { getToolCategories, getTools } from "../api/tools-api";

export interface GroupedTools {
  category: string;
  tools: Tool[];
}

export interface UseToolsResult {
  tools: Tool[];
  groupedTools: GroupedTools[];
  categories: string[];
  isLoading: boolean;
  isRefreshing: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

export function useTools(): UseToolsResult {
  const [tools, setTools] = useState<Tool[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const load = useCallback(async (refresh = false) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);

    try {
      const [fetchedTools, fetchedCategories] = await Promise.all([
        getTools(),
        getToolCategories(),
      ]);
      setTools(fetchedTools);
      setCategories(fetchedCategories);
    } catch (err) {
      setError(err instanceof Error ? err : new Error("Failed to load tools"));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const refresh = useCallback(() => load(true), [load]);

  const groupedTools: GroupedTools[] = categories.map((category) => ({
    category,
    tools: tools.filter((t) => t.category === category),
  }));

  // Include tools with categories not in the categories list
  const knownCategories = new Set(categories);
  const uncategorizedTools = tools.filter(
    (t) => !knownCategories.has(t.category),
  );
  if (uncategorizedTools.length > 0) {
    const otherGroup = groupedTools.find((g) => g.category === "other");
    if (otherGroup) {
      otherGroup.tools = [...otherGroup.tools, ...uncategorizedTools];
    } else {
      groupedTools.push({ category: "other", tools: uncategorizedTools });
    }
  }

  return {
    tools,
    groupedTools: groupedTools.filter((g) => g.tools.length > 0),
    categories,
    isLoading,
    isRefreshing,
    error,
    refresh,
  };
}
