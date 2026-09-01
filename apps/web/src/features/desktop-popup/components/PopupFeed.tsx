"use client";

import BlurStack, { type BlurLayer } from "@/components/ui/blur-stack";
import {
  MessageScroller,
  MessageScrollerContent,
  MessageScrollerProvider,
  MessageScrollerViewport,
  useMessageScrollerScrollable,
} from "@/components/ui/message-scroller";
import ChatRenderer from "@/features/chat/components/interface/ChatRenderer";
import PopupPaywallNotice from "./PopupPaywallNotice";
import "../desktop-popup.css";

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
 * The message scroller owns scroll position: it follows streaming content
 * at the live edge and releases when the user scrolls up. Progressive
 * edge blurs appear only while content continues past that edge.
 */
export default function PopupFeed() {
  return (
    <div className="relative h-full">
      <MessageScrollerProvider autoScroll defaultScrollPosition="end">
        <MessageScroller className="h-full">
          {/* Horizontal padding lives on the CONTENT (not the viewport):
              overflow clips at the scroller's padding edge, which was
              slicing the iMessage bubble tails on both sides. */}
          <MessageScrollerViewport className="compact-chat no-scrollbar">
            <MessageScrollerContent
              data-popup-feed-content
              // Equal 32px breathing room on all four sides. gap-3 keeps the
              // turns readable now that action/follow-up rows (which used to
              // provide the separation) are gone in compact mode.
              className="gap-3 p-8"
            >
              <ChatRenderer compact />
              <PopupPaywallNotice />
            </MessageScrollerContent>
          </MessageScrollerViewport>
        </MessageScroller>
        <PopupEdgeBlurs />
      </MessageScrollerProvider>
    </div>
  );
}

/**
 * Progressive edge blurs — instant (150ms) and only while content actually
 * continues past that edge. Driven by the scroller's own scrollable state,
 * which the primitive keeps fresh on scroll AND on content resize (streamed
 * tokens grow the transcript without a scroll event), so the indicators
 * never go stale mid-stream.
 */
function PopupEdgeBlurs() {
  const { start: scrolled, end: moreBelow } = useMessageScrollerScrollable();

  return (
    <>
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
    </>
  );
}
