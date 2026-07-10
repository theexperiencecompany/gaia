"use client";

import { useCallback, useEffect, useState } from "react";

import { apiService } from "@/lib/api/service";

type TodoFacet = "deliverable" | "notes" | "log";

interface UseTodoCanvasOptions {
  /** Fetch immediately on mount instead of waiting for `fetchContent()` to be called. */
  auto?: boolean;
  /**
   * Which facet to read. Defaults to the legacy `/canvas` alias (the notes
   * facet). Approval previews MUST read `deliverable` — that is the exact
   * content Approve releases, not GAIA's working memory.
   */
  facet?: TodoFacet;
}

/**
 * Fetches a tracked todo's facet content. Shared by `WorkLogSection` (notes),
 * `TodoProposalActions` (deliverable) and the artifact reader so every
 * consumer reads the same content and retry behavior.
 */
export function useTodoCanvas(
  todoId: string,
  options: UseTodoCanvasOptions = {},
) {
  const { auto = false, facet } = options;
  const [content, setContent] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [hasError, setHasError] = useState(false);

  // Re-fetch if we have neither content nor a prior successful load, so a
  // failed read can be retried simply by calling fetchContent again.
  const fetchContent = useCallback(async () => {
    if (content !== null) return;
    setIsLoading(true);
    setHasError(false);
    try {
      const path = facet
        ? `/todos/${todoId}/facets/${facet}`
        : `/todos/${todoId}/canvas`;
      const res = await apiService.get<{ content: string }>(path, {
        silent: true,
      });
      setContent(res.content);
    } catch {
      setHasError(true);
    } finally {
      setIsLoading(false);
    }
  }, [todoId, facet, content]);

  useEffect(() => {
    if (auto) {
      fetchContent();
    }
  }, [auto, fetchContent]);

  return { content, isLoading, hasError, fetchContent };
}
