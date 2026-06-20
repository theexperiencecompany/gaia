"use client";

import type { Components } from "streamdown";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { formatJsonLikeString, normalizeValue } from "@/utils/jsonFormatters";

interface CompactMarkdownProps {
  content: unknown;
}

// Compact heading/list/spacing scale for the tool-output card. Everything else
// (GFM, tables, syntax-highlighted code, links, math) comes from the canonical
// MarkdownRenderer, so there's ONE markdown pipeline instead of two. These
// overrides win over MarkdownRenderer's chat-bubble defaults because Tailwind
// Typography styles via zero-specificity :where(), and the merged `components`
// map applies ours last.
const COMPACT_COMPONENTS: Components = {
  h1: ({ children, ...props }) => (
    <h1
      className="mt-2 mb-1 text-base font-semibold text-zinc-100 first:mt-0"
      {...props}
    >
      {children}
    </h1>
  ),
  h2: ({ children, ...props }) => (
    <h2
      className="mt-2 mb-1 text-sm font-semibold text-zinc-200 first:mt-0"
      {...props}
    >
      {children}
    </h2>
  ),
  h3: ({ children, ...props }) => (
    <h3
      className="mt-1.5 mb-0.5 text-[13px] font-semibold text-zinc-200 first:mt-0"
      {...props}
    >
      {children}
    </h3>
  ),
  h4: ({ children, ...props }) => (
    <h4
      className="mt-1.5 mb-0.5 text-xs font-semibold text-zinc-300 first:mt-0"
      {...props}
    >
      {children}
    </h4>
  ),
  h5: ({ children, ...props }) => (
    <h5
      className="mt-1.5 mb-0.5 text-[11px] font-semibold text-zinc-400 first:mt-0"
      {...props}
    >
      {children}
    </h5>
  ),
  h6: ({ children, ...props }) => (
    <h6
      className="mt-1.5 mb-0.5 text-[11px] font-medium uppercase tracking-wide text-zinc-500 first:mt-0"
      {...props}
    >
      {children}
    </h6>
  ),
  p: ({ ...props }) => <p className="mb-1 last:mb-0" {...props} />,
  ul: ({ ...props }) => (
    <ul className="my-1 list-disc space-y-0.5 pl-4" {...props} />
  ),
  ol: ({ ...props }) => (
    <ol className="my-1 list-decimal space-y-0.5 pl-4" {...props} />
  ),
  li: ({ ...props }) => <li className="leading-snug" {...props} />,
};

/**
 * Compact display for structured data and markdown content in tool-output cards.
 * - Objects/Arrays or JSON-like strings: pretty-printed in a <pre>.
 * - Other strings: markdown via the shared MarkdownRenderer, scaled compact.
 */
export function CompactMarkdown({ content }: CompactMarkdownProps) {
  const { data, isStructured } = normalizeValue(content);

  // Structured data isn't markdown — keep the pretty-printed JSON view.
  if (isStructured) {
    const displayText =
      typeof data === "string"
        ? formatJsonLikeString(data)
        : JSON.stringify(data, null, 2);

    return (
      <pre className="bg-zinc-900/50 rounded-xl p-3 max-h-60 overflow-y-auto text-xs text-zinc-400 whitespace-pre-wrap wrap-break-word w-fit max-w-prose">
        {displayText}
      </pre>
    );
  }

  return (
    <div className="bg-zinc-900/50 rounded-xl p-3 max-h-60 overflow-y-auto w-fit max-w-prose">
      <MarkdownRenderer
        content={String(data)}
        className="text-xs text-zinc-400 leading-relaxed"
        hideCodeToolbar
        components={COMPACT_COMPONENTS}
      />
    </div>
  );
}
