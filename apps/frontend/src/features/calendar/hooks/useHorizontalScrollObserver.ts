import {
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

export interface ScrollMetrics {
  scrollLeft: number;
  scrollWidth: number;
  clientWidth: number;
  visibleStartIndex: number;
  visibleEndIndex: number;
  shouldLoadPast: boolean;
  shouldLoadFuture: boolean;
}

const LOAD_THRESHOLD_DAYS = 10; // Load when within 10 days (1 week) of edge
const DEBOUNCE_MS = 150; // Faster response time

export const useHorizontalScrollObserver = (
  scrollRef: RefObject<HTMLDivElement | null>,
  columnWidth: number,
  dates: Date[],
): ScrollMetrics => {
  const totalDays = dates.length;

  const [metrics, setMetrics] = useState<ScrollMetrics>({
    scrollLeft: 0,
    scrollWidth: 0,
    clientWidth: 0,
    visibleStartIndex: 0,
    visibleEndIndex: 0,
    shouldLoadPast: false,
    shouldLoadFuture: false,
  });

  const debounceTimer = useRef<NodeJS.Timeout | undefined>(undefined);
  const hasScrolledRef = useRef<boolean>(false);

  const calculateMetrics = useCallback(() => {
    const container = scrollRef.current;
    if (!container || columnWidth === 0) return;

    const scrollLeft = container.scrollLeft;
    const scrollWidth = container.scrollWidth;
    const clientWidth = container.clientWidth;

    // Calculate visible date indices
    const visibleStartIndex = Math.floor(scrollLeft / columnWidth);
    const visibleEndIndex = Math.ceil((scrollLeft + clientWidth) / columnWidth);

    // Trigger loading when approaching edges (using <= and >= to be more aggressive)
    const shouldLoadPast =
      hasScrolledRef.current && visibleStartIndex <= LOAD_THRESHOLD_DAYS;
    const shouldLoadFuture =
      hasScrolledRef.current &&
      visibleEndIndex >= totalDays - LOAD_THRESHOLD_DAYS;

    setMetrics({
      scrollLeft,
      scrollWidth,
      clientWidth,
      visibleStartIndex,
      visibleEndIndex,
      shouldLoadPast,
      shouldLoadFuture,
    });
  }, [scrollRef, columnWidth, totalDays]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const handleScroll = () => {
      // Mark that user has scrolled
      hasScrolledRef.current = true;

      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
      }

      debounceTimer.current = setTimeout(() => {
        calculateMetrics();
      }, DEBOUNCE_MS);
    };

    container.addEventListener("scroll", handleScroll, { passive: true });

    // Initial calculation
    calculateMetrics();

    return () => {
      container.removeEventListener("scroll", handleScroll);
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
      }
    };
  }, [calculateMetrics, scrollRef]);

  // Recalculate when column width or total days change
  useEffect(() => {
    calculateMetrics();
  }, [columnWidth, totalDays, calculateMetrics]);

  return metrics;
};
