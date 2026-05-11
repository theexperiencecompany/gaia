"use client";

import { type RefObject, useEffect, useState } from "react";

export function useIntersectionObserver(
  ref: RefObject<HTMLDivElement | null>,
  options: IntersectionObserverInit = { threshold: 0.1 },
): boolean {
  const [isIntersecting, setIntersecting] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) setIntersecting(true);
      // setIntersecting(entry.isIntersecting);
    }, options);

    if (ref?.current) {
      observer.observe(ref.current);
    }

    return () => {
      observer.disconnect();
    };
  }, [ref, options]);

  return isIntersecting;
}
