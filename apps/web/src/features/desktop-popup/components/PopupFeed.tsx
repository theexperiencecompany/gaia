"use client";

import { useEffect, useRef } from "react";
import ChatRenderer from "@/features/chat/components/interface/ChatRenderer";
import { useConversation } from "@/features/chat/hooks/useConversation";

/** Distance from the bottom (px) within which auto-scroll stays engaged. */
const STICK_THRESHOLD_PX = 80;

/**
 * The conversation surface below the composer — its own glass container,
 * shown only once there is something to read. Reuses the full
 * `ChatRenderer` pipeline (compact mode: no avatars, full-width bubbles)
 * and sticks to the bottom while content streams in, unless the user has
 * scrolled up.
 */
export default function PopupFeed() {
  const { convoMessages } = useConversation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const hasMessages = (convoMessages?.length ?? 0) > 0;

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
    <div
      ref={scrollRef}
      className={
        hasMessages
          ? "min-h-0 flex-1 overflow-y-auto rounded-2xl bg-white/5 backdrop-blur-xl px-3"
          : "hidden"
      }
    >
      <div ref={contentRef} className="flex flex-col gap-1 py-3">
        <ChatRenderer compact />
      </div>
    </div>
  );
}
