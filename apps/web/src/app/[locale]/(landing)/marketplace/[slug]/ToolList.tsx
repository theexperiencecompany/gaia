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
    // Measure a description the first time it scrolls into view; one
    // observer for the whole list.
    const observer = new IntersectionObserver(
      (entries) => {
        const found: string[] = [];
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          observer.unobserve(entry.target);
          const element = entry.target as HTMLElement;
          const key = keyOf.get(element);
          if (key && element.scrollHeight > element.clientHeight)
            found.push(key);
        }
        if (found.length > 0) {
          setClamped((previous) => new Set([...previous, ...found]));
        }
      },
      // Ahead of the box's edge, so a toggle is in place before its card shows.
      { root: scrollRef.current, rootMargin: "200px 0px" },
    );
    for (const element of keyOf.keys()) observer.observe(element);
    return () => observer.disconnect();
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
                  variant="ghost"
                  size="sm"
                  onPress={() => toggle(key)}
                  className="mt-1 h-auto min-w-0 px-2 py-1 text-xs text-zinc-500 data-[hover=true]:bg-transparent data-[hover=true]:text-zinc-300"
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
