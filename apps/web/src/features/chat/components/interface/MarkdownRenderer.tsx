import "katex/dist/katex.min.css";

import Image from "next/image";
import type React from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkSmartypants from "remark-smartypants";
import remarkSupersub from "remark-supersub";

import CodeBlock from "@/features/chat/components/code-block/CodeBlock";
import CustomAnchor from "@/features/chat/components/code-block/CustomAnchor";
import { cn } from "@/lib";
import { useImageDialog } from "@/stores/uiStore";

const sanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    div: [
      ...(defaultSchema.attributes?.div || []),
      ["className", "math", "math-display"],
    ],
    span: [
      ...(defaultSchema.attributes?.span || []),
      ["className", "math", "math-inline"],
    ],
    code: [
      ...(defaultSchema.attributes?.code || []),
      ["className", /^language-/],
    ],
  },
};

export interface MarkdownRendererProps {
  content: string;
  className?: string;
  isStreaming?: boolean;
}

const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  className,
  isStreaming,
}) => {
  const { openDialog } = useImageDialog();

  return (
    <div
      className={cn(
        "prose dark:prose-invert fadein-style max-w-none text-white",
        className,
      )}
    >
      <ReactMarkdown
        components={{
          code: ({ className, children, ...props }) => (
            <CodeBlock className={className} {...props}>
              {children}
            </CodeBlock>
          ),
          h1: ({ ...props }) => (
            <h1 className="mt-6 mb-4 text-3xl font-bold" {...props} />
          ),
          h2: ({ ...props }) => (
            <h2 className="mt-5 mb-3 text-2xl font-bold" {...props} />
          ),
          h3: ({ ...props }) => (
            <h3 className="mt-4 mb-2 text-xl font-bold" {...props} />
          ),
          ul: ({ ...props }) => (
            <ul className="mb-4 list-disc pl-6" {...props} />
          ),
          ol: ({ ...props }) => (
            <ol className="mb-4 list-decimal pl-6" {...props} />
          ),
          a: ({ href, children }) => (
            <CustomAnchor href={href} isStreaming={isStreaming}>
              {children}
            </CustomAnchor>
          ),
          blockquote: ({ ...props }) => (
            <blockquote
              className="my-2 border-gray-300 bg-gray-300/10 py-3 pl-4 italic"
              {...props}
            />
          ),
          hr: ({ ...props }) => (
            <hr className="my-8 border-t border-zinc-700" {...props} />
          ),
          p: ({ ...props }) => <p className="mb-4 last:mb-0" {...props} />,
          li: ({ ...props }) => <li className="mb-2" {...props} />,
          img: ({ ...props }) => (
            <Image
              width={500}
              height={500}
              alt="image"
              className="mx-auto my-4 cursor-pointer rounded-xl bg-zinc-900 object-contain transition hover:opacity-80"
              src={props.src as string}
              onClick={() => openDialog(props.src as string)}
            />
          ),
          pre: ({ ...props }) => (
            <pre className="font-serif! text-wrap" {...props} />
          ),
          table: ({ ...props }) => (
            <div className="overflow-x-auto">
              <table
                className="min-w-full border-collapse border-zinc-600"
                {...props}
              />
            </div>
          ),
          thead: ({ ...props }) => (
            <thead
              className="bg-opacity-20 border border-zinc-700 bg-zinc-700"
              {...props}
            />
          ),
          tbody: ({ ...props }) => <tbody {...props} />,
          tr: ({ ...props }) => (
            <tr className="border-b border-zinc-600" {...props} />
          ),
          th: ({ ...props }) => (
            <th
              className="border border-zinc-600 px-4 py-2 text-left font-bold"
              {...props}
            />
          ),
          td: ({ ...props }) => (
            <td className="border border-zinc-700 px-4 py-2" {...props} />
          ),
        }}
        remarkPlugins={[
          remarkGfm,
          remarkBreaks,
          remarkMath,
          remarkSmartypants,
          remarkSupersub,
        ]}
        rehypePlugins={[[rehypeSanitize, sanitizeSchema], rehypeKatex]}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

export default MarkdownRenderer;
