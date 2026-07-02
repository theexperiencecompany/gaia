"use client";

import { ArrowDown02Icon } from "@icons";
import {
  MessageScroller as MessageScrollerPrimitive,
  useMessageScroller,
  useMessageScrollerScrollable,
  useMessageScrollerVisibility,
} from "@shadcn/react/message-scroller";
import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Chat transcript scroller built on the @shadcn/react message-scroller
 * primitives. Owns stick-to-bottom behavior: follows the live edge while the
 * reader is at the bottom, disengages when they scroll up, and exposes a
 * scroll-to-end control that appears only when detached from the live edge.
 */

function MessageScrollerProvider(
  props: React.ComponentProps<typeof MessageScrollerPrimitive.Provider>,
) {
  return <MessageScrollerPrimitive.Provider {...props} />;
}

function MessageScroller({
  className,
  ...props
}: React.ComponentProps<typeof MessageScrollerPrimitive.Root>) {
  return (
    <MessageScrollerPrimitive.Root
      data-slot="message-scroller"
      className={cn(
        "group/message-scroller relative flex size-full min-h-0 flex-col overflow-hidden",
        className,
      )}
      {...props}
    />
  );
}

function MessageScrollerViewport({
  className,
  ...props
}: React.ComponentProps<typeof MessageScrollerPrimitive.Viewport>) {
  return (
    <MessageScrollerPrimitive.Viewport
      data-slot="message-scroller-viewport"
      className={cn(
        "size-full min-h-0 min-w-0 overflow-y-auto overscroll-contain",
        className,
      )}
      {...props}
    />
  );
}

function MessageScrollerContent({
  className,
  ...props
}: React.ComponentProps<typeof MessageScrollerPrimitive.Content>) {
  return (
    <MessageScrollerPrimitive.Content
      data-slot="message-scroller-content"
      className={cn("flex h-max min-h-full flex-col", className)}
      {...props}
    />
  );
}

function MessageScrollerItem({
  className,
  scrollAnchor = false,
  ...props
}: React.ComponentProps<typeof MessageScrollerPrimitive.Item>) {
  return (
    <MessageScrollerPrimitive.Item
      data-slot="message-scroller-item"
      scrollAnchor={scrollAnchor}
      className={cn("min-w-0 shrink-0", className)}
      {...props}
    />
  );
}

function MessageScrollerButton({
  direction = "end",
  className,
  ...props
}: React.ComponentProps<typeof MessageScrollerPrimitive.Button>) {
  // Renders the primitive's own <button>: a render-prop HeroUI Button drops
  // the injected onClick (react-aria owns its event wiring), so the control
  // is styled directly with the design system's icon-button tokens instead.
  return (
    <MessageScrollerPrimitive.Button
      data-slot="message-scroller-button"
      direction={direction}
      className={cn(
        "-translate-x-1/2 absolute bottom-4 left-1/2 z-10 flex h-8 w-8 cursor-pointer items-center justify-center rounded-full bg-zinc-800 shadow-md hover:bg-zinc-700",
        // Fade + slide with the primitive's data-active state; inert when hidden.
        "transition-[translate,scale,opacity,background-color] duration-200",
        "data-[active=false]:pointer-events-none data-[active=false]:translate-y-full data-[active=false]:scale-95 data-[active=false]:opacity-0",
        "data-[active=true]:translate-y-0 data-[active=true]:scale-100 data-[active=true]:opacity-100",
        className,
      )}
      {...props}
    >
      <ArrowDown02Icon className="h-5 w-5 text-zinc-400" />
      <span className="sr-only">
        {direction === "end" ? "Scroll to end" : "Scroll to start"}
      </span>
    </MessageScrollerPrimitive.Button>
  );
}

export {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
  useMessageScroller,
  useMessageScrollerScrollable,
  useMessageScrollerVisibility,
};
