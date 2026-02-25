"use client";

import "katex/dist/katex.min.css";

import Image from "next/image";
import type React from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkSmartypants from "remark-smartypants";
import remarkSupersub from "remark-supersub";

import CodeBlock from "@/features/chat/components/code-block/CodeBlock";
import CustomAnchor from "@/features/chat/components/code-block/CustomAnchor";
import { cn } from "@/lib";
import { useImageDialog } from "@/stores/uiStore";

import { slugifyHeading } from "../utils/parseHeadings";

function extractText(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (node !== null && typeof node === "object" && "props" in node) {
    return extractText(
      (node as { props: { children?: React.ReactNode } }).props.children,
    );
  }
  return "";
}

function headingId(children: React.ReactNode): string {
  return slugifyHeading(extractText(children));
}

export default function MarkdownWrapper({ content }: { content: string }) {
  const { openDialog } = useImageDialog();

  return (
    <div
      className={cn(
        "prose dark:prose-invert max-w-none text-[17px] leading-relaxed font-light text-zinc-300",
      )}
    >
      <ReactMarkdown
        components={{
          code: ({ className, children, ...props }) => (
            <CodeBlock className={className} {...props}>
              {children}
            </CodeBlock>
          ),
          h1: ({ children, ...props }) => (
            <h1
              id={headingId(children)}
              className="mt-14 mb-5 text-5xl font-semibold tracking-tight text-zinc-100 scroll-mt-28"
              {...props}
            >
              {children}
            </h1>
          ),
          h2: ({ children, ...props }) => (
            <h2
              id={headingId(children)}
              className="mt-12 mb-4 text-4xl font-semibold tracking-tight text-zinc-100 scroll-mt-28"
              {...props}
            >
              {children}
            </h2>
          ),
          h3: ({ children, ...props }) => (
            <h3
              id={headingId(children)}
              className="mt-10 mb-3 text-3xl font-semibold tracking-tight text-zinc-200 scroll-mt-28"
              {...props}
            >
              {children}
            </h3>
          ),
          ul: ({ ...props }) => (
            <ul className="my-6 list-disc space-y-2 pl-6" {...props} />
          ),
          ol: ({ ...props }) => (
            <ol className="my-6 list-decimal space-y-2 pl-6" {...props} />
          ),
          a: ({ href, children }) => (
            <CustomAnchor href={href}>{children}</CustomAnchor>
          ),
          blockquote: ({ ...props }) => (
            <blockquote
              className="my-6 border-l-2 border-t-0 border-gray-300 bg-gray-300/10 py-4 pl-5 not-italic"
              {...props}
            />
          ),
          hr: ({ ...props }) => (
            <hr className="my-12 border-t border-zinc-800" {...props} />
          ),
          p: ({ ...props }) => (
            <p className="my-5 leading-[1.8] first:mt-0 last:mb-0" {...props} />
          ),
          li: ({ ...props }) => <li className="leading-[1.7]" {...props} />,
          img: ({ ...props }) => (
            <Image
              width={500}
              height={500}
              alt="image"
              className="mx-auto my-8 cursor-pointer rounded-xl bg-zinc-900 object-contain transition hover:opacity-80"
              src={props.src as string}
              onClick={() => openDialog(props.src as string)}
            />
          ),
          pre: ({ ...props }) => (
            <pre className="my-8 font-serif! text-wrap" {...props} />
          ),
          table: ({ ...props }) => (
            <div className="my-8 overflow-x-auto">
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
        rehypePlugins={[rehypeKatex]}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
