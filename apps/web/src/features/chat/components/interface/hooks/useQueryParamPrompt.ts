"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Seeds the composer from a `?q=` deep link once on mount, then strips the
 * param so a reload does not re-fill the box.
 */
export const useQueryParamPrompt = (
  appendToInputRef: React.RefObject<((text: string) => void) | null>,
): void => {
  const router = useRouter();

  useEffect(() => {
    const queryParam = new URLSearchParams(window.location.search).get("q");
    if (queryParam && appendToInputRef.current) {
      appendToInputRef.current(queryParam);
      const url = new URL(window.location.href);
      url.searchParams.delete("q");
      router.replace(url.pathname + url.search, { scroll: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
};
