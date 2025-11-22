import { useCallback, useEffect, useRef, useState } from "react";

import { useIsLoading } from "@/stores/loadingStore";

interface UseScrollBehaviorReturn {
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  scrollToBottom: () => void;
  handleScroll: (event: React.UIEvent) => void;
  shouldShowScrollButton: boolean;
}

export const useScrollBehavior = (
  hasMessages: boolean,
  messageCount?: number,
): UseScrollBehaviorReturn => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [shouldAutoScroll, setShouldAutoScroll] = useState(true);
  const [shouldShowScrollButton, setShouldShowScrollButton] = useState(false);
  const BOTTOM_THRESHOLD = 50;
  const isLoading = useIsLoading();

  const scrollToBottom = useCallback(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({
        top: scrollContainerRef.current.scrollHeight,
        behavior: "smooth",
      });
      setShouldAutoScroll(true);
      setShouldShowScrollButton(false);
    }
  }, []);

  const handleScroll = useCallback(
    (event: React.UIEvent) => {
      if (!hasMessages) return;

      const target = event.target as HTMLDivElement;
      const { scrollTop, scrollHeight, clientHeight } = target;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
      const isNearBottom = distanceFromBottom <= BOTTOM_THRESHOLD;

      setShouldAutoScroll(isNearBottom);
      setShouldShowScrollButton(!isNearBottom && scrollHeight > clientHeight);
    },
    [hasMessages, BOTTOM_THRESHOLD],
  );

  // Auto-scroll when new messages arrive (only if user is at bottom)
  useEffect(() => {
    if (!hasMessages || !messageCount || !shouldAutoScroll) return;

    scrollContainerRef.current?.scrollTo({
      top: scrollContainerRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messageCount, shouldAutoScroll, hasMessages]);

  // Auto-scroll when AI response finishes streaming
  useEffect(() => {
    if (!hasMessages || isLoading) return;

    // Small delay to ensure DOM is updated with final content
    const timeoutId = setTimeout(() => {
      if (shouldAutoScroll && scrollContainerRef.current) {
        scrollContainerRef.current.scrollTo({
          top: scrollContainerRef.current.scrollHeight,
          behavior: "smooth",
        });
      }
    }, 100);

    return () => clearTimeout(timeoutId);
  }, [isLoading, shouldAutoScroll, hasMessages]);

  return {
    scrollContainerRef,
    scrollToBottom,
    handleScroll,
    shouldShowScrollButton,
  };
};
