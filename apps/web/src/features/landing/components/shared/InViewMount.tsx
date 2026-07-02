"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";

interface InViewMountProps {
  children: ReactNode;
  /**
   * Reserve vertical space before the content mounts so the lazy mount doesn't
   * cause a layout shift. Should roughly match the section's rendered height.
   */
  minHeight?: string;
  /**
   * Start mounting this far before the placeholder enters the viewport. Keep
   * small (or 0) so content immediately below a full-screen hero is not mounted
   * on initial load.
   */
  rootMargin?: string;
  className?: string;
}

/**
 * Defers MOUNTING its children until the placeholder scrolls near the viewport.
 *
 * `next/dynamic` only defers downloading the chunk — the component still mounts,
 * hydrates and executes immediately on the client, so its JS runs during the
 * initial-load critical path. This wrapper keeps that render/execution cost off
 * the initial load entirely: heavy, below-the-fold, non-indexed visual demos
 * only run when the user is about to see them.
 *
 * SSR-safe: server and the first client render both show the empty
 * (placeholder) state, so there is no hydration mismatch. Use only for content
 * that is NOT important for SEO (the indexed copy/tables/FAQ stay eagerly
 * server-rendered).
 */
export function InViewMount({
  children,
  minHeight = "60vh",
  rootMargin = "0px",
  className,
}: InViewMountProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [show, setShow] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setShow(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setShow(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [rootMargin]);

  return (
    <div
      ref={ref}
      className={className}
      style={show ? undefined : { minHeight }}
    >
      {show ? children : null}
    </div>
  );
}
