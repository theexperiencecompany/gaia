import type { MemoryEntry, MemoryListResponse } from "@shared/api/generated";
import { useCallback, useEffect, useState } from "react";
import { memoryApi } from "@/features/memory/api/memoryApi";
import { MEMORY_PAGE_SIZE } from "@/features/memory/constants";

const SEARCH_DEBOUNCE_MS = 250;

/**
 * The memory list's data: the current page, plus a debounced server-side
 * search across every memory (not just the loaded page) while a query is set.
 */
export function useMemoryListData() {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<MemoryListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MemoryEntry[] | null>(
    null,
  );

  const fetchPage = useCallback(async (pageToLoad: number) => {
    setLoading(true);
    try {
      const response = await memoryApi.listMemories({
        page: pageToLoad,
        pageSize: MEMORY_PAGE_SIZE,
      });
      setData(response);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPage(page);
  }, [fetchPage, page]);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setSearchResults(null);
      return;
    }
    let active = true;
    const handle = setTimeout(async () => {
      try {
        const result = await memoryApi.searchMemories(trimmed);
        if (active) setSearchResults(result.memories);
      } catch {
        if (active) setSearchResults([]);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      active = false;
      clearTimeout(handle);
    };
  }, [query]);

  /** Re-read the page and, while searching, the search results. */
  const refresh = useCallback(() => {
    fetchPage(page);
    if (query.trim()) {
      memoryApi
        .searchMemories(query.trim())
        .then((result) => setSearchResults(result.memories))
        .catch(() => setSearchResults([]));
    }
  }, [fetchPage, page, query]);

  /** Drop one memory from whatever list currently shows it. */
  const removeLocally = useCallback((memoryId: string | null) => {
    if (!memoryId) return;
    setData((previous) =>
      previous
        ? {
            ...previous,
            memories: previous.memories.filter((m) => m.id !== memoryId),
            total_count: Math.max(previous.total_count - 1, 0),
          }
        : previous,
    );
    setSearchResults(
      (previous) => previous?.filter((m) => m.id !== memoryId) ?? previous,
    );
  }, []);

  const isSearching = query.trim().length > 0;
  const totalCount = data?.total_count ?? 0;
  return {
    page,
    setPage,
    query,
    setQuery,
    isSearching,
    loading: isSearching ? searchResults === null : loading,
    memories: isSearching ? (searchResults ?? []) : (data?.memories ?? []),
    totalCount,
    totalPages: Math.max(1, Math.ceil(totalCount / MEMORY_PAGE_SIZE)),
    refresh,
    removeLocally,
  };
}
