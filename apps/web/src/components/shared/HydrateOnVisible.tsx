"use client";

import {
  type ReactNode,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

/** Start rendering a deferred section this far before it scrolls into view. */
const HYDRATE_AHEAD_MARGIN = "100% 0px";
/** Stop holding the server height after this long even if the content never reaches it. */
const HOLD_HEIGHT_MAX_MS = 3000;

const unsubscribeNothing = () => undefined;
// The hydration state never changes under a mounted component, so nothing to subscribe to.
const subscribeNever = () => unsubscribeNothing;

/** True while React hydrates server HTML (it reads the server snapshot then), false in a client render. */
function useIsHydrating(): boolean {
  return useSyncExternalStore(
    subscribeNever,
    () => false,
    () => true,
  );
}

/**
 * Keep a below-the-fold section's server HTML inert until it nears the
 * viewport, then render it for real. Skipping its hydration takes that work
 * off the page-load main thread; the markup on screen never changes.
 *
 * Mounted by a client navigation instead, it renders its children at once.
 */
export function HydrateOnVisible({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const isHydrating = useIsHydrating();
  // Server render and hydration both read the server snapshot, so only the global tells them apart; the
  // mismatch is the mechanism: the inert div below keeps the server HTML (suppressHydrationWarning).
  const [active, setActive] = useState(
    // react-doctor-disable-next-line react-doctor/no-hydration-branch-on-browser-global
    () => typeof window === "undefined" || !isHydrating,
  );
  // The server markup's height, held while the client render swaps in: a lazy
  // section shows its loading fallback for a moment, and a shorter page would
  // shift everything below it and jump the scroll position.
  const [heldHeight, setHeldHeight] = useState<number | null>(null);

  useEffect(() => {
    const node = ref.current;
    if (active || !node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          setHeldHeight(node.offsetHeight);
          setActive(true);
        }
      },
      { rootMargin: HYDRATE_AHEAD_MARGIN },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [active]);

  useEffect(() => {
    const node = ref.current;
    if (heldHeight === null || !node) return;
    const startedAt = performance.now();
    let frame = requestAnimationFrame(function release() {
      const contentHeight =
        node.firstElementChild?.getBoundingClientRect().height;
      const settled =
        contentHeight !== undefined && contentHeight >= heldHeight - 1;
      if (settled || performance.now() - startedAt > HOLD_HEIGHT_MAX_MS) {
        setHeldHeight(null);
        return;
      }
      frame = requestAnimationFrame(release);
    });
    return () => cancelAnimationFrame(frame);
  }, [heldHeight]);

  if (active) {
    return (
      <div
        ref={ref}
        style={heldHeight === null ? undefined : { minHeight: heldHeight }}
      >
        {children}
      </div>
    );
  }
  // React does not touch an element's existing DOM when it hydrates with
  // dangerouslySetInnerHTML, so the server-rendered section stays as it is.
  return (
    <div
      ref={ref}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: "" }}
    />
  );
}
