import Image from "next/image";
import type React from "react";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkSmartypants from "remark-smartypants";
import remarkSupersub from "remark-supersub";

import CodeBlock from "@/features/chat/components/code-block/CodeBlock";
import CustomAnchor from "@/features/chat/components/code-block/CustomAnchor";

export const sharedRemarkPlugins = [
  remarkGfm,
  remarkBreaks,
  remarkMath,
  remarkSmartypants,
  remarkSupersub,
];

export const sharedMarkdownComponents = {
  code: ({
    className,
    children,
    ...props
  }: React.HTMLAttributes<HTMLElement>) => (
    <CodeBlock className={className} {...props}>
      {children}
    </CodeBlock>
  ),

  pre: ({ ...props }: React.HTMLAttributes<HTMLElement>) => (
    <pre className="font-serif! text-wrap" {...props} />
  ),

  thead: ({ ...props }: React.HTMLAttributes<HTMLTableSectionElement>) => (
    <thead
      className="bg-opacity-20 border border-zinc-700 bg-zinc-700"
      {...props}
    />
  ),

  tbody: ({ ...props }: React.HTMLAttributes<HTMLTableSectionElement>) => (
    <tbody {...props} />
  ),

  tr: ({ ...props }: React.HTMLAttributes<HTMLTableRowElement>) => (
    <tr className="border-b border-zinc-600" {...props} />
  ),

  th: ({ ...props }: React.HTMLAttributes<HTMLTableCellElement>) => (
    <th
      className="border border-zinc-600 px-4 py-2 text-left font-bold"
      {...props}
    />
  ),

  td: ({ ...props }: React.HTMLAttributes<HTMLTableCellElement>) => (
    <td className="border border-zinc-700 px-4 py-2" {...props} />
  ),
} as const;

export function makeImgComponent(
  openDialog: (src: string) => void,
  className: string,
) {
  return function ImgComponent({
    ...props
  }: React.ImgHTMLAttributes<HTMLImageElement>) {
    return (
      <Image
        width={500}
        height={500}
        alt="image"
        className={className}
        src={props.src as string}
        onClick={() => openDialog(props.src as string)}
      />
    );
  };
}

export function makeAnchorComponent(isStreaming?: boolean) {
  return function AnchorComponent({
    href,
    children,
  }: {
    href?: string;
    children?: React.ReactNode;
  }) {
    return (
      <CustomAnchor href={href} isStreaming={isStreaming}>
        {children}
      </CustomAnchor>
    );
  };
}
