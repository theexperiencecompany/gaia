"use client";

import { Button } from "@heroui/button";
import { useEffect, useRef, useState } from "react";
import { displayToolDescription, displayToolName } from "./toolCopy";

interface ToolCardProps {
  readonly name: string;
  readonly description?: string | null;
  readonly integrationName: string;
}

export function ToolCard({
  name,
  description,
  integrationName,
}: ToolCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [isClamped, setIsClamped] = useState(false);
  const descriptionRef = useRef<HTMLParagraphElement>(null);
  const label = displayToolName(name, integrationName);
  const copy = description
    ? displayToolDescription(description, integrationName)
    : description;

  // Detect whether the 2-line clamp actually truncates the description, so the
  // toggle only renders when there is hidden content to reveal.
  useEffect(() => {
    const element = descriptionRef.current;
    if (!element) return;
    setIsClamped(element.scrollHeight > element.clientHeight);
  }, [copy]);

  return (
    <div className="rounded-xl bg-zinc-800/50 p-3">
      <p className="font-medium text-zinc-200">{label}</p>
      {copy && (
        <>
          <p
            ref={descriptionRef}
            className={`text-sm text-zinc-400 ${expanded ? "" : "line-clamp-2"}`}
          >
            {copy}
          </p>
          {(isClamped || expanded) && (
            <Button
              variant="light"
              size="sm"
              radius="full"
              onPress={() => setExpanded((value) => !value)}
              className="mt-1 h-auto min-w-0 px-2 py-1 text-xs text-zinc-500 data-[hover=true]:bg-transparent data-[hover=true]:text-zinc-300"
            >
              {expanded ? "View less" : "View more"}
            </Button>
          )}
        </>
      )}
    </div>
  );
}
