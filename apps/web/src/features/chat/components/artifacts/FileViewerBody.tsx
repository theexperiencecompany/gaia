"use client";

import { Spinner } from "@heroui/react";
import Image from "next/image";

import { AgentHtmlFrame } from "@/components/shared/AgentHtmlFrame";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { getExtension } from "@/features/chat/utils/fileExtension";

export type ViewMode = "preview" | "source";

function getLanguage(filename: string): string {
  const ext = getExtension(filename);
  const langMap: Record<string, string> = {
    py: "python",
    js: "javascript",
    ts: "typescript",
    tsx: "tsx",
    jsx: "jsx",
    json: "json",
    css: "css",
    html: "html",
    htm: "html",
    xml: "xml",
    yaml: "yaml",
    yml: "yaml",
    sql: "sql",
    sh: "bash",
    bash: "bash",
    md: "markdown",
    rs: "rust",
    go: "go",
    java: "java",
    rb: "ruby",
    php: "php",
    swift: "swift",
    kt: "kotlin",
    c: "c",
    cpp: "cpp",
    h: "c",
    tex: "latex",
    csv: "csv",
    txt: "text",
  };
  return langMap[ext] || "text";
}

// Fills the panel: an agent's page often sizes itself to the viewport.
const HTML_PREVIEW_STYLES =
  "<style>html, body { height: 100%; margin: 0; padding: 0; overscroll-behavior: contain; } body { min-height: 100%; }</style>";

/** A file's text, rendered by its type or shown as highlighted source. */
export function FileContentRenderer({
  content,
  contentType,
  filename,
  viewMode,
}: {
  content: string;
  contentType: string;
  filename: string;
  viewMode: ViewMode;
}) {
  const markdownClassName = "px-3 pb-2";

  if (viewMode === "source") {
    const language = getLanguage(filename);
    return (
      <MarkdownRenderer
        className={markdownClassName}
        hideCodeToolbar
        content={`\`\`\`${language}\n${content}\n\`\`\``}
      />
    );
  }

  if (contentType === "text/markdown") {
    return <MarkdownRenderer className={markdownClassName} content={content} />;
  }

  if (contentType === "text/html") {
    return (
      <div className="h-full min-h-0">
        <AgentHtmlFrame
          trust="page"
          title={filename}
          html={`${HTML_PREVIEW_STYLES}${content}`}
          className="block h-full w-full bg-white"
        />
      </div>
    );
  }

  if (contentType === "text/x-latex") {
    return (
      <MarkdownRenderer
        className={markdownClassName}
        content={`$$\n${content}\n$$`}
      />
    );
  }

  const language = getLanguage(filename);
  return (
    <MarkdownRenderer
      className={markdownClassName}
      content={`\`\`\`${language}\n${content}\n\`\`\``}
    />
  );
}

interface FileViewerBodyProps {
  isImage: boolean;
  isPdf: boolean;
  loading: boolean;
  error: boolean;
  content: string | null;
  contentType: string;
  filename: string;
  /** URL the browser loads images and PDFs from directly. */
  fileUrl: string;
  viewMode: ViewMode;
}

export function FileViewerBody({
  isImage,
  isPdf,
  loading,
  error,
  content,
  contentType,
  filename,
  fileUrl,
  viewMode,
}: Readonly<FileViewerBodyProps>) {
  if (isImage) {
    return (
      <div className="flex h-full items-center justify-center bg-zinc-950 p-4">
        <Image
          src={fileUrl}
          alt={filename}
          width={500}
          height={500}
          className="max-h-full max-w-full object-contain"
          unoptimized
        />
      </div>
    );
  }
  if (isPdf) {
    // Native PDF viewer — never fetch as text (old fallback streamed the
    // binary as a string, slow on cold R2 reads, rendered as garbage). Fully
    // sandboxed like the HTML preview; downloads stay via the panel's own button.
    return (
      <iframe
        title={filename}
        src={fileUrl}
        className="h-full w-full bg-white"
        sandbox=""
      />
    );
  }
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-red-400">Failed to load file</p>
      </div>
    );
  }
  if (content === null) {
    return null;
  }
  return (
    <FileContentRenderer
      content={content}
      contentType={contentType}
      filename={filename}
      viewMode={viewMode}
    />
  );
}
