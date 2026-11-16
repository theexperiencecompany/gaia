"use client";

import { ScrollShadow } from "@heroui/react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";

export interface ToolListItem {
  readonly key: string;
  readonly label: string;
  /** The description, rendered from markdown on the server; null when the tool has none. */
  readonly description: ReactNode;
}

/**
 * The tool cards in their 400px scroll box. Integrations list up to ~800
 * tools, so the cards are plain markup owned by this one component: a card's
 * "View more" toggle mounts only once the card is on screen and its
 * description turns out clamped, instead of one hydrated component per tool.
 */
export function ToolList({
  items,
}: {
  readonly items: readonly ToolListItem[];
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const descriptionRefs = useRef(new Map<string, HTMLDivElement>());
  const [clamped, setClamped] = useState<ReadonlySet<string>>(new Set());
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    const keyOf = new Map<Element, string>();
    for (const [key, element] of descriptionRefs.current)
      keyOf.set(element, key);
    // Measure each description again whenever its box resizes (a narrower
    // viewport can clamp one that fit), so its toggle tracks the current width.
    const resizeObserver = new ResizeObserver((entries) => {
      const changes = new Map<string, boolean>();
      for (const { target } of entries) {
        const key = keyOf.get(target);
        if (key) changes.set(key, target.scrollHeight > target.clientHeight);
      }
      setClamped((previous) => {
        const next = new Set(previous);
        for (const [key, isClamped] of changes) {
          if (isClamped) next.add(key);
          else next.delete(key);
        }
        return next;
      });
    });
    // Start measuring a description once it nears the scroll box's viewport,
    // so ~800 off-screen cards are never laid out up front.
    const intersectionObserver = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          intersectionObserver.unobserve(entry.target);
          resizeObserver.observe(entry.target);
        }
      },
      // Ahead of the box's edge, so a toggle is in place before its card shows.
      { root: scrollRef.current, rootMargin: "200px 0px" },
    );
    for (const element of keyOf.keys()) intersectionObserver.observe(element);
    return () => {
      intersectionObserver.disconnect();
      resizeObserver.disconnect();
    };
  }, []);

  const toggle = (key: string) =>
    setExpanded((previous) => {
      const next = new Set(previous);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  return (
    <ScrollShadow ref={scrollRef} className="max-h-100">
      <div className="grid grid-cols-2 gap-4">
        {items.map(({ key, label, description }) => {
          const isExpanded = expanded.has(key);
          return (
            // content-visibility skips layout and paint for cards scrolled out of the box.
            <div
              key={key}
              className="rounded-xl bg-zinc-800/50 p-3 [content-visibility:auto] [contain-intrinsic-size:auto_88px]"
            >
              <p className="font-medium text-zinc-200">{label}</p>
              {description ? (
                <div
                  ref={(element) => {
                    if (element) descriptionRefs.current.set(key, element);
                    else descriptionRefs.current.delete(key);
                  }}
                  className={`text-sm text-zinc-400 ${isExpanded ? "" : "line-clamp-2"}`}
                >
                  {description}
                </div>
              ) : null}
              {clamped.has(key) || isExpanded ? (
                <GaiaButton
                  shape="pill"
                  variant="text"
                  size="sm"
                  tone="faint"
                  hoverTone="dim"
                  onPress={() => toggle(key)}
                  className="mt-1 text-xs"
                >
                  {isExpanded ? "View less" : "View more"}
                </GaiaButton>
              ) : null}
            </div>
          );
        })}
      </div>
    </ScrollShadow>
  );
}
