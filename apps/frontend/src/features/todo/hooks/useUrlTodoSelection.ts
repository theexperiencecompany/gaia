"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/**
 * Custom hook for managing todo selection via URL query parameters
 * Provides a consistent way to handle todo selection across all pages
 */
export function useUrlTodoSelection() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  // Get the currently selected todo ID from URL
  const selectedTodoId = searchParams.get("todoId");

  // Helper function to update URL with todo ID
  const updateTodoInUrl = useCallback(
    (todoId: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      const currentTodoId = params.get("todoId");

      // Don't update URL if it's already correct
      if (currentTodoId === todoId) {
        return;
      }

      if (todoId) {
        params.set("todoId", todoId);
      } else {
        params.delete("todoId");
      }

      // Get current pathname and update URL
      const newUrl = params.toString()
        ? `${pathname}?${params.toString()}`
        : pathname;
      router.replace(newUrl, { scroll: false });
    },
    [router, searchParams, pathname],
  );

  // Helper function to select a todo
  const selectTodo = useCallback(
    (todoId: string | null) => {
      updateTodoInUrl(todoId);
    },
    [updateTodoInUrl],
  );

  // Helper function to clear selection
  const clearSelection = useCallback(() => {
    updateTodoInUrl(null);
  }, [updateTodoInUrl]);

  return {
    selectedTodoId,
    selectTodo,
    clearSelection,
    isSelected: (todoId: string) => selectedTodoId === todoId,
  };
}
