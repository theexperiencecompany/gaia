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
/** Default BlurStack stops already read bottom-heavy — reuse for the
 * bottom edge while more content waits below. */
const BOTTOM_BLUR_LAYERS: BlurLayer[] = [
  { blur: 0.5, maskStops: [0, 12.5, 25, 37.5], zIndex: 1 },
  { blur: 1, maskStops: [12.5, 25, 37.5, 50], zIndex: 2 },
  { blur: 2, maskStops: [25, 37.5, 50, 62.5], zIndex: 3 },
  { blur: 4, maskStops: [37.5, 50, 62.5, 75], zIndex: 4 },
  { blur: 8, maskStops: [50, 62.5, 75, 87.5], zIndex: 5 },
  { blur: 16, maskStops: [62.5, 75, 87.5, 100], zIndex: 6 },
  { blur: 32, maskStops: [75, 87.5, 100, 100], zIndex: 7 },
];

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
  const [moreBelow, setMoreBelow] = useState(false);

  useEffect(() => {
    const scroller = scrollRef.current;
    const content = contentRef.current;
    if (!scroller || !content) return;
    let raf = 0;

    // Wheel-up is explicit user intent: release the bottom-stick so
    // streaming growth can't yank the view back down. Reaching the
    // bottom again re-engages it.
    const handleWheel = (event: WheelEvent) => {
      if (event.deltaY < 0) stickToBottomRef.current = false;
    };
    const handleScroll = () => {
      const distance =
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      if (distance < STICK_THRESHOLD_PX) stickToBottomRef.current = true;
      setScrolled(scroller.scrollTop > 0);
      setMoreBelow(distance > 4);
    };
    scroller.addEventListener("wheel", handleWheel, { passive: true });
    scroller.addEventListener("scroll", handleScroll, { passive: true });

    // Instant, rAF-coalesced follow during content growth — queueing
    // smooth scrolls every resize tick fights the user and stutters.
    const observer = new ResizeObserver(() => {
      if (!stickToBottomRef.current) return;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        scroller.scrollTop = scroller.scrollHeight;
      });
    });
    observer.observe(content);

    return () => {
      cancelAnimationFrame(raf);
      scroller.removeEventListener("wheel", handleWheel);
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
          // Equal 32px breathing room on all four sides. gap-3 keeps the
          // turns readable now that action/follow-up rows (which used to
          // provide the separation) are gone in compact mode.
          className="flex flex-col gap-3 p-8"
        >
          <ChatRenderer compact />
        </div>
      </div>
      {/* Progressive edge blurs — instant (150ms) and only while content
          actually continues past that edge. */}
      <div
        className={`pointer-events-none absolute inset-x-0 top-0 h-14 transition-opacity duration-150 ${scrolled ? "opacity-100" : "opacity-0"}`}
      >
        <BlurStack config={TOP_BLUR_LAYERS} className="absolute inset-0" />
      </div>
      <div
        className={`pointer-events-none absolute inset-x-0 bottom-0 h-14 transition-opacity duration-150 ${moreBelow ? "opacity-100" : "opacity-0"}`}
      >
        <BlurStack config={BOTTOM_BLUR_LAYERS} className="absolute inset-0" />
      </div>
    </div>
  );
}
