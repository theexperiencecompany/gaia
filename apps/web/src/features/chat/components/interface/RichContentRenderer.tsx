"use client";

import { type ContentSegment, parseOpenUISegments } from "@shared/utils";
import dynamic from "next/dynamic";
import { Fragment, type ReactNode, useId } from "react";

import { cn } from "@/lib/utils";
import MarkdownRenderer from "./MarkdownRenderer";

// OpenUI components render browser-only (charts/maps) and share bg-zinc-800 with
// the chat bubble, so they mount OUTSIDE any bubble wrapper — see bubbles/bot/CLAUDE.md.
const OpenUIRenderer = dynamic(() => import("./OpenUIRenderer"), {
  ssr: false,
});

interface RichContentRendererProps {
  /** Markdown that may contain `:::openui` fenced blocks. */
  content: string;
  /** Streaming source (chat); keeps an unclosed fence in its shimmer state. */
  isStreaming?: boolean;
  /** Extra classes for the wrapping column. */
  className?: string;
  /**
   * Override how a prose segment renders. Chat wraps prose in iMessage bubbles;
   * omit it to render prose as a plain document (the artifact reader default).
   */
  renderMarkdown?: (
    segment: ContentSegment,
    index: number,
    isLastMarkdown: boolean,
  ) => ReactNode;
}

/**
 * Splits `content` into prose and `:::openui` segments, rendering prose via
 * MarkdownRenderer and fenced blocks via OpenUIRenderer — the single place that
 * turns markdown + OpenUI into React, shared by chat and the artifact reader.
 */
export default function RichContentRenderer({
  content,
  isStreaming = false,
  className,
  renderMarkdown,
}: Readonly<RichContentRendererProps>) {
  const baseId = useId();
  const segments = parseOpenUISegments(content, isStreaming);
  const lastMarkdownIndex = segments.reduce(
    (acc, segment, index) =>
      segment.type === "markdown" && segment.content.trim() ? index : acc,
    -1,
  );

  return (
    <div className={cn("flex flex-col", className)}>
      {segments.map((segment, index) => {
        // Keyed by the segment's position in the source text, not its array
        // index: that position is stable across streaming re-parses (text
        // only ever grows past it) but changes on a real edit/regenerate, so
        // React remounts instead of reusing the wrong node.
        const key = `${baseId}-seg-${segment.start}`;

        if (segment.type === "openui") {
          return (
            <OpenUIRenderer
              key={key}
              code={segment.content}
              isStreaming={isStreaming && !segment.isComplete}
            />
          );
        }

        if (!segment.content.trim()) return null;

        if (renderMarkdown) {
          return (
            <Fragment key={key}>
              {renderMarkdown(segment, index, index === lastMarkdownIndex)}
            </Fragment>
          );
        }

        return (
          <MarkdownRenderer
            key={key}
            content={segment.content}
            isStreaming={isStreaming}
          />
        );
      })}
    </div>
  );
}
