"use client";
import { useCallback, useEffect, useRef } from "react";

import type { MailTab } from "@/types/features/mailTypes";

import { useInfiniteEmails } from "./useInfiniteEmails";

export function useTableInfiniteScroll(tab: MailTab) {
  const { emails, isLoading, hasNextPage, fetchNextPage, error } =
    useInfiniteEmails(tab);

  const observerRef = useRef<IntersectionObserver | null>(null);
  const isFetchingMore = useRef(false);

  const bottomRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }

      if (!node) return;

      observerRef.current = new IntersectionObserver(
        (entries) => {
          if (
            entries[0]?.isIntersecting &&
            hasNextPage &&
            !isFetchingMore.current
          ) {
            isFetchingMore.current = true;
            fetchNextPage().finally(() => {
              isFetchingMore.current = false;
            });
          }
        },
        { threshold: 0.1 },
      );

      observerRef.current.observe(node);
    },
    [hasNextPage, fetchNextPage],
  );

  useEffect(() => {
    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, []);

  return {
    emails,
    isLoading,
    hasNextPage: hasNextPage ?? false,
    bottomRef,
    isLoadingMore: isFetchingMore.current,
    error,
  };
}
