import "katex/dist/katex.min.css";
import "streamdown/styles.css";

import Image from "next/image";
import { useParams } from "next/navigation";
import type React from "react";
import { useMemo } from "react";
import rehypeKatex from "rehype-katex";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkSmartypants from "remark-smartypants";
import remarkSupersub from "remark-supersub";
import {
  type AllowedTags,
  type AnimateOptions,
  type Components,
  defaultUrlTransform,
  type PluginConfig,
  Streamdown,
  type UrlTransform,
} from "streamdown";

import { resolveArtifactSrc } from "@/features/chat/api/sessionFilesApi";
import CodeBlock from "@/features/chat/components/code-block/CodeBlock";
import CustomAnchor from "@/features/chat/components/code-block/CustomAnchor";
import { cn } from "@/lib/utils";
import { useImageDialog } from "@/stores/uiStore";

// Streamdown always sanitizes (rehype-sanitize defaultSchema, then rehype-harden)
// and that pass is not user-replaceable. allowedTags is merged INTO that schema,
// so it is how we keep the artifacts our pipeline depends on from being stripped:
//  - `className` on span/div — the `math math-inline` / `math math-display`
//    placeholders remark-math emits. rehype-katex runs AFTER sanitize (via the
//    plugins.math slot) and reads them to render math; if the class is stripped
//    first, math never renders.
//  - `className`/`metastring` on code — the `language-xxx` class CodeBlock reads
//    to choose a highlighter, plus the fenced-code meta string.
const ALLOWED_TAGS: AllowedTags = {
  span: ["className"],
  div: ["className"],
  code: ["className", "metastring"],
};

// Blur-in per word. The library owns the batching: animation-fill-mode "both"
// starts words invisible and ends them visible, so even when a fast model dumps
// many tokens in one commit the simultaneous mount reads as intentional. blurIn
// + a slightly longer 250ms ease-out masks those batch arrivals smoothly.
const ANIMATION: AnimateOptions = {
  animation: "blurIn",
  duration: 250,
  easing: "ease-out",
  // Custom stagger disabled — fall back to streamdown's 40ms default.
  // stagger: 80,
};

// Math goes through streamdown's plugin slot rather than the rehype list so
// rehype-katex runs after sanitize/harden — its output is trusted markup that
// would otherwise be stripped. remark-math parses `$…$`; rehype-katex renders it.
const PLUGINS: PluginConfig = {
  math: {
    name: "katex",
    type: "math",
    remarkPlugin: remarkMath,
    rehypePlugin: rehypeKatex,
  },
};

// gfm is included explicitly: passing remarkPlugins replaces streamdown's default
// set, so we restate it here alongside the GAIA flavors (line breaks, smart
// punctuation, super/subscript).
const REMARK_PLUGINS = [
  remarkGfm,
  remarkBreaks,
  remarkSmartypants,
  remarkSupersub,
];

interface MarkdownImageProps {
  src?: string;
  alt?: string;
  conversationId: string | undefined;
  onOpen: (src: string) => void;
}

const MarkdownImage: React.FC<MarkdownImageProps> = ({
  src,
  alt,
  conversationId,
  onOpen,
}) => {
  const resolved = resolveArtifactSrc(src, conversationId) ?? src;
  if (!resolved) return null;
  return (
    <Image
      width={500}
      height={500}
      alt={alt || "image"}
      className="mx-auto my-4 cursor-pointer rounded-xl bg-zinc-900 object-contain transition hover:opacity-80"
      src={resolved}
      onClick={() => onOpen(resolved)}
      unoptimized
    />
  );
};

const MarkdownImageNode: React.FC<{ src?: string | Blob; alt?: string }> = ({
  src,
  alt,
}) => {
  const { openDialog } = useImageDialog();
  const params = useParams<{ id?: string }>();
  // Markdown image sources are always URL strings; ignore the Blob case the
  // react-markdown prop type technically allows.
  const imageSrc = typeof src === "string" ? src : undefined;
  return (
    <MarkdownImage
      src={imageSrc}
      alt={alt}
      conversationId={params?.id}
      onOpen={openDialog}
    />
  );
};

export interface MarkdownRendererProps {
  content: string;
  className?: string;
  isStreaming?: boolean;
  hideCodeToolbar?: boolean;
  /**
   * Render dark text for a light-colored bubble (the `imessage-from-me` user
   * bubble is `#00bbff` with black text by design). Defaults to the dark-bubble
   * treatment (inverted prose, white text) used by the bot bubble and modals.
   */
  lightBackground?: boolean;
  /** Per-element overrides merged over the default component map. */
  components?: Components;
  /**
   * Extra URL protocols allowed on links (e.g. ["mention"]), for callers
   * whose component overrides give such links a custom rendering.
   */
  extraLinkProtocols?: string[];
}

const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  className,
  isStreaming,
  hideCodeToolbar,
  components,
  extraLinkProtocols,
  lightBackground,
}) => {
  const urlTransform = useMemo<UrlTransform>(() => {
    if (!extraLinkProtocols?.length) return defaultUrlTransform;
    return (url, key, node) =>
      extraLinkProtocols.some((protocol) => url.startsWith(`${protocol}:`))
        ? url
        : defaultUrlTransform(url, key, node);
  }, [extraLinkProtocols]);

  // Memoized so its identity is stable across streaming ticks. A fresh
  // components object each render defeats streamdown's per-block memoization,
  // forcing every block (math, code, tables) to re-render on every token.
  const mergedComponents = useMemo<Components>(
    () => ({
      code: ({ className, children, ...props }) => (
        <CodeBlock
          className={className}
          hideToolbar={hideCodeToolbar}
          {...props}
        >
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
      ul: ({ ...props }) => <ul className="mb-4 list-disc pl-6" {...props} />,
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
      img: MarkdownImageNode,
      pre: ({ ...props }) => (
        <pre className="font-serif! text-wrap" {...props} />
      ),
      table: ({ ...props }) => (
        <div className="markdown-table my-4 overflow-x-auto rounded-3xl bg-zinc-900 p-3">
          <style>{`
                .markdown-table table { border-separate: separate; border-spacing: 0; }
                .markdown-table tbody tr:first-child td:first-child { border-top-left-radius: 0.75rem; }
                .markdown-table tbody tr:first-child td:last-child { border-top-right-radius: 0.75rem; }
                .markdown-table tbody tr:last-child td:first-child { border-bottom-left-radius: 0.75rem; }
                .markdown-table tbody tr:last-child td:last-child { border-bottom-right-radius: 0.75rem; }
                .markdown-table tbody tr:last-child td { border-bottom: none; }
                .markdown-table tbody tr:hover td { background-color: #27272A80; }
              `}</style>
          <table
            className="min-w-full border-separate border-spacing-0 text-sm"
            {...props}
          />
        </div>
      ),
      thead: ({ ...props }) => <thead {...props} />,
      tbody: ({ ...props }) => <tbody {...props} />,
      tr: ({ ...props }) => <tr className="transition-colors" {...props} />,
      th: ({ ...props }) => (
        <th
          className="px-3 pb-3 pt-1 text-left text-xs font-medium tracking-wide text-zinc-500 bg-zinc-900"
          {...props}
        />
      ),
      td: ({ ...props }) => (
        <td
          className="border-b border-zinc-700/50 bg-zinc-800 px-3 py-3 text-zinc-100"
          {...props}
        />
      ),
      ...components,
    }),
    [hideCodeToolbar, isStreaming, components],
  );

  return (
    <div
      className={cn(
        "prose fadein-style max-w-none",
        lightBackground
          ? "text-black [--tw-prose-body:#000] [--tw-prose-headings:#000] [--tw-prose-bold:#000] [--tw-prose-links:#000] [--tw-prose-code:#000]"
          : "dark:prose-invert text-white",
        className,
      )}
    >
      <Streamdown
        components={mergedComponents}
        remarkPlugins={REMARK_PLUGINS}
        plugins={PLUGINS}
        allowedTags={ALLOWED_TAGS}
        urlTransform={urlTransform}
        isAnimating={isStreaming}
        animated={ANIMATION}
        parseIncompleteMarkdown
        controls={false}
      >
        {content}
      </Streamdown>
    </div>
  );
};

export default MarkdownRenderer;
