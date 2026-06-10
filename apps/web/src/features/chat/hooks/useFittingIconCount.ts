import { useEffect, useRef, useState } from "react";

// Width budget per icon: the 14px glyph + the gap-1 (4px) separating them.
const ICON_STEP_PX = 18;
// Space reserved for the "+N" overflow badge when not all icons fit.
const OVERFLOW_BADGE_PX = 30;

/**
 * Compute how many fixed-size icons fit inside a flexible container, measured
 * from the container's own width (so it adapts to sidebar/viewport changes, not
 * just viewport breakpoints). Returns a ref to attach to the icon container and
 * the number of icons that fit; the caller shows `total - visibleCount` as "+N".
 */
export function useFittingIconCount(total: number) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [visibleCount, setVisibleCount] = useState(total);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const compute = () => {
      const width = el.clientWidth;
      if (width <= 0) return;
      const fitAll = Math.floor(width / ICON_STEP_PX);
      if (fitAll >= total) {
        setVisibleCount(total);
        return;
      }
      // Overflowing: reserve room for the "+N" badge, but still show at least
      // one icon whenever an icon and the badge fit together (never a clipped
      // icon, never a lonely badge).
      const fitWithBadge = Math.floor(
        (width - OVERFLOW_BADGE_PX) / ICON_STEP_PX,
      );
      const canShowIconWithBadge = width >= ICON_STEP_PX + OVERFLOW_BADGE_PX;
      setVisibleCount(
        Math.min(total, Math.max(canShowIconWithBadge ? 1 : 0, fitWithBadge)),
      );
    };

    compute();
    const observer = new ResizeObserver(compute);
    observer.observe(el);
    return () => observer.disconnect();
  }, [total]);

  return { containerRef, visibleCount };
}
