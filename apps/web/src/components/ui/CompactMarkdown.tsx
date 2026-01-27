"use client";

import ReactMarkdown from "react-markdown";
import { formatJsonLikeString, normalizeValue } from "@/utils/jsonFormatters";

interface CompactMarkdownProps {
  content: unknown;
}

/**
 * Compact display for structured data and markdown content.
 * Accepts any value and automatically formats it appropriately:
 * - Objects/Arrays: Pretty-printed JSON
 * - Strings that look like JSON: Formatted with indentation (even if truncated)
 * - Other strings: Markdown rendering
 */
export function CompactMarkdown({ content }: CompactMarkdownProps) {
  const { data, isStructured } = normalizeValue(content);

  // For structured data, render as preformatted text
  if (isStructured) {
    // If data is already a string (e.g., truncated JSON), format it
    // Otherwise, pretty-print the object/array
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

  // For text content, use react-markdown
  const textContent = String(data);

  return (
    <div className="bg-zinc-900/50 rounded-xl p-3 max-h-60 overflow-y-auto text-xs text-zinc-400 leading-relaxed w-fit max-w-prose">
      <ReactMarkdown
        components={{
          p: ({ children }) => <p className="mb-1 last:mb-0">{children}</p>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline font-normal"
            >
              {children}
            </a>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold">{children}</strong>
          ),
          em: ({ children }) => <em>{children}</em>,
          code: ({ children }) => (
            <code className="bg-zinc-800 px-1 py-0.5 rounded text-[11px]">
              {children}
            </code>
          ),
          pre: ({ children }) => (
            <pre className="bg-zinc-800 rounded p-2 my-1 overflow-x-auto text-[11px] whitespace-pre-wrap">
              {children}
            </pre>
          ),
          ul: ({ children }) => <ul className="list-disc pl-4">{children}</ul>,
          ol: ({ children }) => (
            <ol className="list-decimal pl-4">{children}</ol>
          ),
          li: ({ children }) => <li>{children}</li>,
          h1: ({ children }) => (
            <h1 className="font-semibold mb-1">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="font-semibold mb-1">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="font-medium mb-1">{children}</h3>
          ),
        }}
      >
        {textContent}
      </ReactMarkdown>
    </div>
  );
}
