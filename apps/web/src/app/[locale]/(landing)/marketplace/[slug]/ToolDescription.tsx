import type { ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import type { Processor } from "unified";

// links, images, quotes and rules are unwrapped to their text
const ALLOWED_ELEMENTS = [
  "p",
  "strong",
  "em",
  "code",
  "pre",
  "ul",
  "ol",
  "li",
  "br",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
];

function SubheadingParagraph({ children }: { children?: ReactNode }) {
  return <p className="mb-2 font-medium text-zinc-300 last:mb-0">{children}</p>;
}

const COMPONENTS: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  code: ({ children }) => (
    <code className="font-mono text-zinc-300">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="mb-2 whitespace-pre-wrap last:mb-0">{children}</pre>
  ),
  ul: ({ children }) => (
    <ul className="mb-2 list-disc pl-4 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal pl-4 last:mb-0">{children}</ol>
  ),
  h1: SubheadingParagraph,
  h2: SubheadingParagraph,
  h3: SubheadingParagraph,
  h4: SubheadingParagraph,
  h5: SubheadingParagraph,
  h6: SubheadingParagraph,
};

/** Read docstring indentation as prose; tool descriptions are often Python docstrings. */
function remarkNoIndentedCode(this: Processor) {
  const data = this.data();
  data.micromarkExtensions = [
    ...(data.micromarkExtensions ?? []),
    { disable: { null: ["codeIndented"] } },
  ];
}

/** Render a tool description, which the API writes as markdown for the model. */
export function ToolDescription({ markdown }: { readonly markdown: string }) {
  return (
    <ReactMarkdown
      allowedElements={ALLOWED_ELEMENTS}
      unwrapDisallowed
      remarkPlugins={[remarkNoIndentedCode]}
      components={COMPONENTS}
    >
      {markdown}
    </ReactMarkdown>
  );
}
