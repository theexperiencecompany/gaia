"use client";

import { useEffect, useRef } from "react";
import ChatRenderer from "@/features/chat/components/interface/ChatRenderer";

/** Distance from the bottom (px) within which auto-scroll stays engaged. */
const STICK_THRESHOLD_PX = 80;

/**
 * Scrollable mini chat feed. Reuses the full `ChatRenderer` pipeline —
 * message bubbles, tool cards, pop-in animations — and sticks to the
 * bottom while content streams in, unless the user has scrolled up.
 */
export default function PopupFeed() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

  useEffect(() => {
    const scroller = scrollRef.current;
    const content = contentRef.current;
    if (!scroller || !content) return;

    const handleScroll = () => {
      stickToBottomRef.current =
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <
        STICK_THRESHOLD_PX;
    };
    scroller.addEventListener("scroll", handleScroll, { passive: true });

    const observer = new ResizeObserver(() => {
      if (stickToBottomRef.current) scroller.scrollTop = scroller.scrollHeight;
    });
    observer.observe(content);

    return () => {
      scroller.removeEventListener("scroll", handleScroll);
      observer.disconnect();
    };
  }, []);

  return (
    <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-3">
      <div ref={contentRef} className="flex flex-col gap-1 py-2">
        <ChatRenderer />
      </div>
    </div>
  );
}
