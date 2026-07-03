"use client";

import { useCallback, useEffect, useState } from "react";

import { apiService } from "@/lib/api/service";

interface UseTodoCanvasOptions {
  /** Fetch immediately on mount instead of waiting for `fetchContent()` to be called. */
  auto?: boolean;
}

/**
 * Fetches a todo's `canvas.md` (GAIA's working memory / work log for that
 * task). Shared by `CanvasViewer` (click-to-open modal) and `WorkLogSection`
 * (always-rendered inline section) so both read the same content and retry
 * behavior instead of forking the fetch logic.
 */
export function useTodoCanvas(
  todoId: string,
  options: UseTodoCanvasOptions = {},
) {
  const { auto = false } = options;
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
      const res = await apiService.get<{ content: string }>(
        `/todos/${todoId}/canvas`,
        { silent: true },
      );
      setContent(res.content);
    } catch {
      setHasError(true);
    } finally {
      setIsLoading(false);
    }
  }, [todoId, content]);

  useEffect(() => {
    if (auto) {
      fetchContent();
    }
  }, [auto, fetchContent]);

  return { content, isLoading, hasError, fetchContent };
}
