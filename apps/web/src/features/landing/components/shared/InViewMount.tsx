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
 * Defers MOUNTING its children until the placeholder scrolls near the
 * viewport — unlike `next/dynamic`, which only defers the chunk download
 * while still mounting/hydrating immediately.
 *
 * SSR-safe (server and first client render both show the empty placeholder).
 * Use only for content that isn't important for SEO.
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
