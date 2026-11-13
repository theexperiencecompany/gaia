"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";

interface ToolCardProps {
  readonly label: string;
  /** The description, rendered from markdown on the server; omitted when the tool has none. */
  readonly children?: ReactNode;
}

export function ToolCard({ label, children }: ToolCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [isClamped, setIsClamped] = useState(false);
  const descriptionRef = useRef<HTMLDivElement>(null);

  // Detect whether the 2-line clamp actually truncates the description, so the
  // toggle only renders when there is hidden content to reveal.
  useEffect(() => {
    const element = descriptionRef.current;
    if (!element) return;
    setIsClamped(element.scrollHeight > element.clientHeight);
  }, []);

  return (
    // content-visibility skips layout and paint for the cards scrolled out of the 400px box.
    <div className="rounded-xl bg-zinc-800/50 p-3 [content-visibility:auto] [contain-intrinsic-size:auto_88px]">
      <p className="font-medium text-zinc-200">{label}</p>
      {children && (
        <>
          <div
            ref={descriptionRef}
            className={`text-sm text-zinc-400 ${expanded ? "" : "line-clamp-2"}`}
          >
            {children}
          </div>
          {(isClamped || expanded) && (
            <GaiaButton
              shape="pill"
              variant="ghost"
              size="sm"
              onPress={() => setExpanded((value) => !value)}
              className="mt-1 h-auto min-w-0 px-2 py-1 text-xs text-zinc-500 data-[hover=true]:bg-transparent data-[hover=true]:text-zinc-300"
            >
              {expanded ? "View less" : "View more"}
            </GaiaButton>
          )}
        </>
      )}
    </div>
  );
}
