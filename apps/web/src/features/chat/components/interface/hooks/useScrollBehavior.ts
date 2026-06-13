import { useCallback } from "react";
import { useStickToBottom } from "use-stick-to-bottom";

interface UseScrollBehaviorReturn {
  scrollContainerRef: (node: HTMLElement | null) => void;
  contentRef: (node: HTMLElement | null) => void;
  scrollToBottom: () => void;
  shouldShowScrollButton: boolean;
}

/**
 * Wraps `use-stick-to-bottom` to keep the chat viewport pinned to the latest
 * content. Unlike the previous message-count-driven approach, this follows
 * *content height* growth via a ResizeObserver — so streaming tokens, tool
 * cards rendering in, images loading, and follow-up chips appearing all keep
 * the view at the bottom. It also tracks user-initiated scroll-up internally
 * (`escapedFromLock`), so the user is never yanked back down while reading.
 *
 * `scrollContainerRef` → the scroll container (overflow-y-auto).
 * `contentRef` → the wrapper around the growing message content (observed).
 */
export const useScrollBehavior = (): UseScrollBehaviorReturn => {
  const { scrollRef, contentRef, scrollToBottom, isAtBottom } =
    useStickToBottom({ initial: "instant", resize: "smooth" });

  const handleScrollToBottom = useCallback(() => {
    scrollToBottom();
  }, [scrollToBottom]);

  return {
    scrollContainerRef: scrollRef,
    contentRef,
    scrollToBottom: handleScrollToBottom,
    shouldShowScrollButton: !isAtBottom,
  };
};
