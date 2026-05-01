"use client";

import { memo } from "react";
import { TodoLinkPreview } from "./TodoLinkPreview";

// Matches http:// and https:// URLs, excluding trailing sentence punctuation
const URL_REGEX = /https?:\/\/[^\s<>"']+(?<![.,!?;:])/g;

interface TitleSegment {
  type: "text" | "url";
  value: string;
}

function parseTitle(title: string): TitleSegment[] {
  const segments: TitleSegment[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  // Reset lastIndex before exec loop
  URL_REGEX.lastIndex = 0;

  while ((match = URL_REGEX.exec(title)) !== null) {
    const matchStart = match.index;
    const matchEnd = matchStart + match[0].length;

    if (matchStart > lastIndex) {
      segments.push({ type: "text", value: title.slice(lastIndex, matchStart) });
    }

    segments.push({ type: "url", value: match[0] });
    lastIndex = matchEnd;
  }

  if (lastIndex < title.length) {
    segments.push({ type: "text", value: title.slice(lastIndex) });
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
  const segments = parseTitle(title);

  // If no URLs found, render plain text
  if (segments.length === 1 && segments[0].type === "text") {
    return <span className={className}>{title}</span>;
  }

  return (
    <span className={className}>
      {segments.map((segment, index) => {
        if (segment.type === "url") {
          return <TodoLinkPreview key={index} href={segment.value} />;
        }
        return <span key={index}>{segment.value}</span>;
      })}
    </span>
  );
});
