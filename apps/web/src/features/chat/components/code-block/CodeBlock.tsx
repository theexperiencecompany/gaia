"use client";

import dynamic from "next/dynamic";
import type React from "react";
import { type ReactNode, useEffect, useState } from "react";

import { useLoading } from "@/features/chat/hooks/useLoading";

import CopyButton from "./CopyButton";
import DownloadButton from "./DownloadButton";

// Dynamic imports — keep heavy syntax/diagram deps out of the SSR bundle.
// On Cloudflare Workers via OpenNext, every server-rendered import lands in
// handler.mjs (no runtime chunk loading). Forcing ssr:false here means the
// initial HTML is a tiny placeholder; Prism + refractor + mermaid only load
// on the client. The mermaid SDK init now lives in FlowchartPreview so the
// `import("mermaid")` is unreachable from any server-render code path.
const StandardCodeBlock = dynamic(() => import("./StandardCodeBlock"), {
  ssr: false,
  loading: () => (
    <pre className="my-2 overflow-x-auto rounded-xl bg-zinc-900 p-4 text-xs text-zinc-400" />
  ),
});

const MermaidTabs = dynamic(() => import("./MermaidTabs"), {
  ssr: false,
  loading: () => (
    <div className="flex h-40 items-center justify-center text-sm text-gray-500">
      Loading diagram...
    </div>
  ),
});

interface CodeBlockProps extends React.HTMLAttributes<HTMLElement> {
  inline?: boolean;
  className?: string;
  children: ReactNode;
  hideToolbar?: boolean;
}

const CodeBlock: React.FC<CodeBlockProps> = ({
  inline,
  className,
  children,
  hideToolbar,
  ...props
}) => {
  const { isLoading } = useLoading();
  const [activeTab, setActiveTab] = useState("code");
  const [copied, setCopied] = useState(false);

  const match = /language-(\w+)/.exec(className || "");
  const isMermaid = match && match[1] === "mermaid";

  // Automatically switch to preview mode once loading is done.
  // FlowchartPreview re-runs `mermaid.contentLoaded()` whenever its children
  // change, so we no longer need to call it from here.
  useEffect(() => {
    if (!isLoading) setActiveTab("preview");
  }, [isLoading]);

  const handleCopy = () => {
    navigator.clipboard.writeText(String(children).replace(/\n$/, ""));
    setCopied(true);
    setTimeout(() => setCopied(false), 4000);
  };

  if (isMermaid) {
    return (
      <div className="relative my-3 flex w-[40vw] max-w-[30vw] flex-col gap-0 overflow-x-visible rounded-t-[10px]! bg-zinc-900 pb-0!">
        <MermaidTabs
          activeTab={activeTab}
          onTabChange={setActiveTab}
          isLoading={isLoading}
          syntaxHighlighterProps={{
            ...props,
            style: props.style as { [key: string]: unknown },
          }}
        >
          {children}
        </MermaidTabs>
        <div className="absolute top-2 right-1 flex items-center gap-1">
          <DownloadButton
            content={String(children)}
            language={match ? match[1] : undefined}
          />
          <CopyButton copied={copied} onPress={handleCopy} />
        </div>
      </div>
    );
  }

  return (
    <>
      {!inline && match ? (
        <StandardCodeBlock
          className={className}
          copied={copied}
          onCopy={handleCopy}
          hideToolbar={hideToolbar}
        >
          {children}
        </StandardCodeBlock>
      ) : (
        <code
          className={`${className} rounded-md bg-zinc-900 px-2 py-1 text-sm text-zinc-400`}
          {...props}
        >
          {children}
        </code>
      )}
    </>
  );
};

export default CodeBlock;
