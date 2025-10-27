import Image from "next/image";
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import CodeBlock from "@/features/chat/components/code-block/CodeBlock";
import CustomAnchor from "@/features/chat/components/code-block/CustomAnchor";
import { cn } from "@/lib";

export interface MarkdownRendererProps {
  content: string;
  className?: string;
}

const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  className,
}) => {
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
            <CustomAnchor href={href}>{children}</CustomAnchor>
          ),
          blockquote: ({ ...props }) => (
            <blockquote
              className="my-8 border-l-3 border-gray-300 bg-gray-300/10 py-5 pl-4 italic"
              {...props}
            />
          ),
          img: ({ ...props }) => (
            <Image
              width={500}
              height={500}
              alt="image"
              className="my-4 object-contain"
              src={props.src as string}
            />
          ),
          pre: ({ ...props }) => (
            <pre className="font-serif! text-wrap" {...props} />
          ),
          table: ({ ...props }) => (
            <div className="overflow-x-auto">
              <table
                className="min-w-full border-collapse border border-zinc-600"
                {...props}
              />
            </div>
          ),
          thead: ({ ...props }) => (
            <thead className="bg-opacity-20 bg-zinc-900" {...props} />
          ),
          tbody: ({ ...props }) => <tbody {...props} />,
          tr: ({ ...props }) => (
            <tr className="border-b border-zinc-600" {...props} />
          ),
          th: ({ ...props }) => (
            <th className="px-4 py-2 text-left font-bold" {...props} />
          ),
          td: ({ ...props }) => <td className="px-4 py-2" {...props} />,
        }}
        remarkPlugins={[remarkGfm]}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

export default MarkdownRenderer;
