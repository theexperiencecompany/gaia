import { type RefObject, useCallback, useRef } from "react";

/**
 * The nearest scrolling ancestor of `sectionRef`, resolved once and cached.
 * An explicit `scroller` (including `null`, meaning the window) skips the
 * DOM walk entirely.
 */
export function useScrollContainer(
  sectionRef: RefObject<HTMLDivElement | null>,
  scroller: HTMLElement | null | undefined,
) {
  const cache = useRef<HTMLElement | null | undefined>(undefined);

  return useCallback((): HTMLElement | null => {
    if (scroller !== undefined) return scroller;
    if (cache.current !== undefined) return cache.current;

    let current = sectionRef.current?.parentElement;
    while (current) {
      const styles = window.getComputedStyle(current);
      if (styles.overflowY === "auto" || styles.overflowY === "scroll") {
        cache.current = current;
        return current;
      }
      current = current.parentElement;
    }
    cache.current = null;
    return null;
  }, [sectionRef, scroller]);
}
