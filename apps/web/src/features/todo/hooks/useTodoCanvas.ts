"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getTodoCanvas,
  getTodoFacet,
  type TodoFacet,
} from "@/features/todo/api/todoApi";

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

  // Always fetch: one hook instance is reused across todo selections (the
  // sidebar swaps props, not components), so a cached read would keep showing
  // the previous todo's content. Re-reading on open is also more correct for
  // GAIA's live working memory, and a failed read retries by itself.
  const fetchContent = useCallback(async () => {
    setIsLoading(true);
    setHasError(false);
    try {
      const res = facet
        ? await getTodoFacet(todoId, facet)
        : await getTodoCanvas(todoId);
      setContent(res.content);
    } catch {
      setHasError(true);
    } finally {
      setIsLoading(false);
    }
  }, [todoId, facet]);

  useEffect(() => {
    if (auto) {
      fetchContent();
    }
  }, [auto, fetchContent]);

  return { content, isLoading, hasError, fetchContent };
}
