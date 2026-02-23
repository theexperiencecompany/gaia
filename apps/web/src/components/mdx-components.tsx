import type { MDXComponents } from "mdx/types";
import Image from "next/image";

export function useMDXComponents(components: MDXComponents): MDXComponents {
  return {
    h1: ({ children }) => (
      <h1 className="mb-6 text-3xl font-bold text-foreground">{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className="mt-8 mb-4 text-2xl font-semibold text-foreground">
        {children}
      </h2>
    ),
    h3: ({ children }) => (
      <h3 className="mt-6 mb-3 text-xl font-semibold text-foreground">
        {children}
      </h3>
    ),
    h4: ({ children }) => (
      <h4 className="mt-4 mb-2 text-lg font-semibold text-foreground">
        {children}
      </h4>
    ),
    h5: ({ children }) => (
      <h5 className="mt-3 mb-2 text-base font-semibold text-foreground">
        {children}
      </h5>
    ),
    h6: ({ children }) => (
      <h6 className="mt-3 mb-2 text-sm font-semibold text-foreground">
        {children}
      </h6>
    ),
    p: ({ children }) => (
      <p className="mb-4 leading-relaxed text-foreground-600">{children}</p>
    ),
    ul: ({ children }) => (
      <ul className="mb-4 ml-6 list-disc space-y-2">{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className="mb-4 ml-6 list-decimal space-y-2">{children}</ol>
    ),
    li: ({ children }) => <li className="text-foreground-600">{children}</li>,
    strong: ({ children }) => (
      <strong className="font-semibold text-foreground">{children}</strong>
    ),
    em: ({ children }) => (
      <em className="text-foreground-600 italic">{children}</em>
    ),
    code: ({ children }) => (
      <code className="rounded bg-surface-900 px-1.5 py-0.5 font-mono text-sm text-foreground dark:bg-surface-200">
        {children}
      </code>
    ),
    pre: ({ children }) => (
      <pre className="mb-4 overflow-x-auto rounded-lg border bg-surface-900 p-4 dark:bg-surface-200">
        {children}
      </pre>
    ),
    blockquote: ({ children }) => (
      <blockquote className="mb-4 border-l-4 border-surface-700 pl-4 text-foreground-600 italic dark:border-surface-400">
        {children}
      </blockquote>
    ),
    a: ({ children, href }) => (
      <a
        href={href}
        className="text-blue-600 hover:underline dark:text-blue-400"
        target="_blank"
        rel="noopener noreferrer"
      >
        {children}
      </a>
    ),
    img: ({ src, alt }) => (
      <>
        <Image
          src={src}
          width={1000}
          height={1000}
          alt={alt}
          className="mb-4 h-auto max-w-full rounded-lg border"
        />
      </>
    ),
    hr: () => <hr className="my-8 border-surface-700 dark:border-surface-400" />,
    table: ({ children }) => (
      <div className="mb-4 overflow-x-auto">
        <table className="min-w-full border-collapse border border-surface-700 dark:border-surface-400">
          {children}
        </table>
      </div>
    ),
    th: ({ children }) => (
      <th className="border border-surface-700 bg-surface-900 px-4 py-2 text-left font-semibold dark:border-surface-400 dark:bg-surface-200">
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td className="border border-surface-700 px-4 py-2 dark:border-surface-400">
        {children}
      </td>
    ),
    ...components,
  };
}
