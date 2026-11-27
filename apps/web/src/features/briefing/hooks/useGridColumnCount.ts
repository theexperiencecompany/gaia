import { type RefObject, useLayoutEffect, useRef, useState } from "react";

/** The tracks a CSS grid lays out right now, re-read as it resizes; null before it is measured. */
export function useGridColumnCount<T extends HTMLElement>(): [
  RefObject<T | null>,
  number | null,
] {
  const ref = useRef<T | null>(null);
  const [columns, setColumns] = useState<number | null>(null);

  useLayoutEffect(() => {
    const grid = ref.current;
    if (!grid) return;
    const measure = () => {
      const tracks = getComputedStyle(grid)
        .gridTemplateColumns.split(" ")
        .filter(Boolean).length;
      setColumns(tracks > 0 ? tracks : null);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    return () => observer.disconnect();
  }, []);

  return [ref, columns];
}
