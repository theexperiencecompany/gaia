"use client";

import dynamic from "next/dynamic";
import type React from "react";
import { type ReactNode, useEffect, useState } from "react";

import { useLoading } from "@/features/chat/hooks/useLoading";

import CopyButton from "./CopyButton";
import DownloadButton from "./DownloadButton";
import StandardCodeBlock from "./StandardCodeBlock";

// Dynamic import for MermaidTabs with loading fallback
const MermaidTabs = dynamic(() => import("./MermaidTabs"), {
  ssr: false,
  loading: () => (
    <div className="flex h-40 items-center justify-center text-sm text-gray-500">
      Loading diagram...
    </div>
  ),
});

// Type for mermaid instance
interface MermaidInstance {
  initialize: (config: object) => void;
  contentLoaded: () => void;
}

// Dynamic import for mermaid library
const useMermaid = () => {
  const [mermaid, setMermaid] = useState<MermaidInstance | null>(null);

  useEffect(() => {
    const loadMermaid = async () => {
      if (!mermaid) {
        const mermaidModule = await import("mermaid");
        mermaidModule.default.initialize({
          startOnLoad: true,
          theme: "dark",
          flowchart: {
            useMaxWidth: true,
            htmlLabels: true,
            curve: "linear",
          },
          // Disable unused diagram types to reduce bundle size
          gantt: {
            useMaxWidth: false,
          },
          journey: {
            useMaxWidth: false,
          },
          timeline: {
            useMaxWidth: false,
          },
          // Disable cytoscape layouts to prevent loading cytoscape
          elk: {
            mergeEdges: false,
          },
        });
        setMermaid(mermaidModule.default);
      }
    };

    loadMermaid();
  }, [mermaid]);

  return mermaid;
};

interface CodeBlockProps extends React.HTMLAttributes<HTMLElement> {
  inline?: boolean;
  className?: string;
  children: ReactNode;
}

const CodeBlock: React.FC<CodeBlockProps> = ({
  inline,
  className,
  children,
  ...props
}) => {
  const { isLoading } = useLoading();
  const [activeTab, setActiveTab] = useState("code");
  const [copied, setCopied] = useState(false);
  const mermaid = useMermaid();

  const match = /language-(\w+)/.exec(className || "");
  const isMermaid = match && match[1] === "mermaid";

  // When loading or tab changes, reload mermaid diagrams.
  useEffect(() => {
    if (mermaid) {
      mermaid.contentLoaded();
    }
  }, [isLoading, activeTab, mermaid]);

  // Automatically switch to preview mode once loading is done.
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
          onTabChange={(key) => {
            setActiveTab(key);
            setTimeout(() => {
              if (mermaid) {
                mermaid.contentLoaded();
              }
            }, 10);
          }}
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
