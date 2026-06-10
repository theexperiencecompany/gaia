"use client";

import { useEffect, useRef, useState } from "react";
import BlurStack, { type BlurLayer } from "@/components/ui/blur-stack";
import ChatRenderer from "@/features/chat/components/interface/ChatRenderer";
import "../desktop-popup.css";

/** Distance from the bottom (px) within which auto-scroll stays engaged. */
const STICK_THRESHOLD_PX = 80;

/**
 * BlurStack layers mirrored for a TOP edge: strongest blur at the very
 * top, dissolving downward — scrolled-away bubbles melt into the glass
 * instead of being cut by an opacity fade.
 */
const TOP_BLUR_LAYERS: BlurLayer[] = [
  { blur: 64, maskStops: [0, 0, 0, 12.5], zIndex: 8 },
  { blur: 32, maskStops: [0, 0, 12.5, 25], zIndex: 7 },
  { blur: 16, maskStops: [0, 12.5, 25, 37.5], zIndex: 6 },
  { blur: 8, maskStops: [12.5, 25, 37.5, 50], zIndex: 5 },
  { blur: 4, maskStops: [25, 37.5, 50, 62.5], zIndex: 4 },
  { blur: 2, maskStops: [37.5, 50, 62.5, 75], zIndex: 3 },
  { blur: 1, maskStops: [50, 62.5, 75, 87.5], zIndex: 2 },
  { blur: 0.5, maskStops: [62.5, 75, 87.5, 100], zIndex: 1 },
];

/**
 * The conversation island — rendered in its own liquid-glass window.
 * Scrollable, smooth-scrolls to follow streaming content (unless the
 * user scrolled up), with a progressive top blur while scrolled.
 */
export default function PopupFeed() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const scroller = scrollRef.current;
    const content = contentRef.current;
    if (!scroller || !content) return;

    const handleScroll = () => {
      stickToBottomRef.current =
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <
        STICK_THRESHOLD_PX;
      setScrolled(scroller.scrollTop > 4);
    };
    scroller.addEventListener("scroll", handleScroll, { passive: true });

    const observer = new ResizeObserver(() => {
      if (stickToBottomRef.current) {
        scroller.scrollTo({
          top: scroller.scrollHeight,
          behavior: "smooth",
        });
      }
    });
    observer.observe(content);

    return () => {
      scroller.removeEventListener("scroll", handleScroll);
      observer.disconnect();
    };
  }, []);

  return (
    <div className="relative h-full">
      {/* Horizontal padding lives on the CONTENT (not the scroller):
          overflow clips at the scroller's padding edge, which was
          slicing the iMessage bubble tails on both sides. */}
      <div
        ref={scrollRef}
        className="compact-chat h-full overflow-y-auto no-scrollbar"
      >
        <div
          ref={contentRef}
          data-popup-feed-content
          className="flex flex-col gap-1 px-3 py-3"
        >
          <ChatRenderer compact />
        </div>
      </div>
      {/* Progressive top blur — only once content has scrolled under it. */}
      <div
        className={`pointer-events-none absolute inset-x-0 top-0 h-14 transition-opacity duration-300 ${scrolled ? "opacity-100" : "opacity-0"}`}
      >
        <BlurStack config={TOP_BLUR_LAYERS} className="absolute inset-0" />
      </div>
    </div>
  );
}
