"use client";

import type { ReactNode } from "react";

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
      <pre className="bg-surface-100/50 rounded-xl p-3 max-h-60 overflow-y-auto text-xs text-foreground-400 whitespace-pre-wrap break-words w-fit max-w-200">
        {displayText}
      </pre>
    );
  }

  // For text content, use react-markdown
  const ReactMarkdown = require("react-markdown").default;
  const textContent = String(data);

  return (
    <div className="bg-surface-100/50 rounded-xl p-3 max-h-60 overflow-y-auto text-xs text-foreground-400 leading-relaxed w-fit max-w-200">
      <ReactMarkdown
        components={{
          p: ({ children }: { children: ReactNode }) => (
            <p className="mb-1 last:mb-0">{children}</p>
          ),
          a: ({ href, children }: { href?: string; children: ReactNode }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline font-normal"
            >
              {children}
            </a>
          ),
          strong: ({ children }: { children: ReactNode }) => (
            <strong className="font-semibold">{children}</strong>
          ),
          em: ({ children }: { children: ReactNode }) => <em>{children}</em>,
          code: ({ children }: { children: ReactNode }) => (
            <code className="bg-surface-200 px-1 py-0.5 rounded text-[11px]">
              {children}
            </code>
          ),
          pre: ({ children }: { children: ReactNode }) => (
            <pre className="bg-surface-200 rounded p-2 my-1 overflow-x-auto text-[11px] whitespace-pre-wrap">
              {children}
            </pre>
          ),
          ul: ({ children }: { children: ReactNode }) => (
            <ul className="list-disc pl-4">{children}</ul>
          ),
          ol: ({ children }: { children: ReactNode }) => (
            <ol className="list-decimal pl-4">{children}</ol>
          ),
          li: ({ children }: { children: ReactNode }) => <li>{children}</li>,
          h1: ({ children }: { children: ReactNode }) => (
            <h1 className="font-semibold mb-1">{children}</h1>
          ),
          h2: ({ children }: { children: ReactNode }) => (
            <h2 className="font-semibold mb-1">{children}</h2>
          ),
          h3: ({ children }: { children: ReactNode }) => (
            <h3 className="font-medium mb-1">{children}</h3>
          ),
        }}
      >
        {textContent}
      </ReactMarkdown>
    </div>
  );
}
