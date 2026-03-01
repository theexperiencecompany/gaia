import "katex/dist/katex.min.css";

import type React from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";

import { cn } from "@/lib";
import {
  makeAnchorComponent,
  makeImgComponent,
  sharedMarkdownComponents,
  sharedRemarkPlugins,
} from "@/lib/markdown/sharedComponents";
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
          ...sharedMarkdownComponents,
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
          a: makeAnchorComponent(isStreaming),
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
          img: makeImgComponent(
            openDialog,
            "mx-auto my-4 cursor-pointer rounded-xl bg-zinc-900 object-contain transition hover:opacity-80",
          ),
          table: ({ ...props }) => (
            <div className="overflow-x-auto">
              <table
                className="min-w-full border-collapse border-zinc-600"
                {...props}
              />
            </div>
          ),
        }}
        remarkPlugins={sharedRemarkPlugins}
        rehypePlugins={[[rehypeSanitize, sanitizeSchema], rehypeKatex]}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

export default MarkdownRenderer;
