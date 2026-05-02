"use client";

import { memo } from "react";
import { TodoLinkPreview } from "./TodoLinkPreview";

interface TitleSegment {
  type: "text" | "url";
  value: string;
  start: number;
}

function parseTitle(title: string): TitleSegment[] {
  // New instance each call — avoids shared lastIndex state across concurrent renders
  const URL_REGEX = /https?:\/\/[^\s<>"']+(?<![.,!?;:])/g;
  const segments: TitleSegment[] = [];
  let lastIndex = 0;
  let match = URL_REGEX.exec(title);

  while (match !== null) {
    const matchStart = match.index;
    const matchEnd = matchStart + match[0].length;

    if (matchStart > lastIndex) {
      segments.push({
        type: "text",
        value: title.slice(lastIndex, matchStart),
        start: lastIndex,
      });
    }

    segments.push({ type: "url", value: match[0], start: matchStart });
    lastIndex = matchEnd;
    match = URL_REGEX.exec(title);
  }

  if (lastIndex < title.length) {
    segments.push({
      type: "text",
      value: title.slice(lastIndex),
      start: lastIndex,
    });
  }

  return segments;
}

interface TodoTitleProps {
  title: string;
  className?: string;
}

export const TodoTitle = memo(function TodoTitle({
  title,
  className,
}: TodoTitleProps) {
  if (!title) {
    return <span className={className}>Untitled</span>;
  }

  const segments = parseTitle(title);

  // If no URLs found, render plain text
  if (segments.length === 1 && segments[0].type === "text") {
    return <span className={className}>{title}</span>;
  }

  return (
    <span className={className}>
      {segments.map((segment) => {
        const key = `${segment.type}:${segment.start}`;
        if (segment.type === "url") {
          return <TodoLinkPreview key={key} href={segment.value} />;
        }
        return <span key={key}>{segment.value}</span>;
      })}
    </span>
  );
});
