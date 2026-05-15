"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import {
  Cancel01Icon,
  CodeIcon,
  Copy01Icon,
  Download01Icon,
  File01Icon,
} from "@icons";
import { formatFileSize } from "@shared/utils";
import { useCallback, useEffect, useState, type WheelEvent } from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { useArtifactText } from "@/features/chat/hooks/useArtifactText";
import { useRightSidebar } from "@/stores/rightSidebarStore";

interface FileViewerPanelProps {
  conversationId: string;
  path: string;
  filename: string;
  contentType: string;
  sizeBytes?: number;
}

type ViewMode = "preview" | "source";

const PREVIEWABLE_CONTENT_TYPES = new Set([
  "text/markdown",
  "text/html",
  "text/x-latex",
]);

function getExtension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() || "";
}

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

function buildHtmlPreviewDocument(content: string): string {
  const previewStyles = `
    <style>
      html, body {
        height: 100%;
        margin: 0;
        padding: 0;
        overscroll-behavior: contain;
      }
      body {
        min-height: 100%;
      }
    </style>
  `;

  const hasHtmlTag = /<html[\s>]/i.test(content);
  const hasHeadTag = /<head[\s>]/i.test(content);

  if (hasHtmlTag) {
    if (hasHeadTag) {
      return content.replace(
        /<head[^>]*>/i,
        (match) => `${match}${previewStyles}`,
      );
    }

    return content.replace(
      /<html[^>]*>/i,
      (match) => `${match}<head>${previewStyles}</head>`,
    );
  }

  return `<!doctype html><html><head><meta charset="utf-8" />${previewStyles}</head><body>${content}</body></html>`;
}

function FileContentRenderer({
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
  const markdownClassName = "px-4 pb-3";

  if (viewMode === "source") {
    const language = getLanguage(filename);
    return (
      <MarkdownRenderer
        className={markdownClassName}
        content={`\`\`\`${language}\n${content}\n\`\`\``}
      />
    );
  }

  if (contentType === "text/markdown") {
    return <MarkdownRenderer className={markdownClassName} content={content} />;
  }

  if (contentType === "text/html") {
    const previewDoc = buildHtmlPreviewDocument(content);

    return (
      <div className="h-full min-h-0">
        <iframe
          title={filename}
          srcDoc={previewDoc}
          className="block h-full w-full border-0 bg-white"
          sandbox=""
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

export default function FileViewerPanel({
  conversationId,
  path,
  filename,
  contentType,
  sizeBytes,
}: FileViewerPanelProps) {
  const {
    text: content,
    loading,
    error,
  } = useArtifactText(conversationId, path);
  const [copied, setCopied] = useState(false);
  const closeSidebar = useRightSidebar((state) => state.close);

  const isPreviewable = PREVIEWABLE_CONTENT_TYPES.has(contentType);

  const [viewMode, setViewMode] = useState<ViewMode>(
    isPreviewable ? "preview" : "source",
  );

  useEffect(() => {
    setViewMode(isPreviewable ? "preview" : "source");
  }, [isPreviewable]);

  const handleCopy = useCallback(async () => {
    if (content === null) return;

    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // no-op
    }
  }, [content]);

  const handleDownload = useCallback(() => {
    if (content === null) return;

    const blob = new Blob([content], { type: contentType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [content, contentType, filename]);

  const ext = getExtension(filename).toUpperCase();
  const sizeLabel =
    sizeBytes !== undefined ? ` · ${formatFileSize(sizeBytes)}` : "";
  const isHtmlPreview = contentType === "text/html" && viewMode === "preview";

  const handleContentWheel = useCallback(
    (event: WheelEvent<HTMLDivElement>) => {
      event.stopPropagation();

      if (isHtmlPreview) {
        event.preventDefault();
        return;
      }

      const container = event.currentTarget;
      const deltaY = event.deltaY;
      const atTop = container.scrollTop <= 0;
      const atBottom =
        container.scrollTop + container.clientHeight >=
        container.scrollHeight - 1;

      if ((deltaY < 0 && atTop) || (deltaY > 0 && atBottom)) {
        event.preventDefault();
      }
    },
    [isHtmlPreview],
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-zinc-950">
      <div className="flex h-14 shrink-0 items-center gap-2 border-b border-zinc-800 bg-zinc-900 px-2">
        {isPreviewable ? (
          <div className="flex rounded-md border border-zinc-700 bg-zinc-950 p-0.5">
            <button
              type="button"
              onClick={() => setViewMode("preview")}
              className={`rounded-sm p-1.5 transition-colors ${viewMode === "preview" ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"}`}
              aria-label="Preview mode"
            >
              <File01Icon size={16} />
            </button>
            <button
              type="button"
              onClick={() => setViewMode("source")}
              className={`rounded-sm p-1.5 transition-colors ${viewMode === "source" ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"}`}
              aria-label="Code mode"
            >
              <CodeIcon size={16} />
            </button>
          </div>
        ) : null}

        <p className="min-w-0 flex-1 truncate text-sm text-zinc-200">
          {filename}
          <span className="text-zinc-500">{` · ${ext || "FILE"}${sizeLabel}`}</span>
        </p>

        {copied ? (
          <span className="text-xs text-emerald-400">Copied</span>
        ) : null}

        <div className="flex items-center gap-0.5">
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onClick={handleCopy}
            aria-label="Copy file"
            isDisabled={content === null}
          >
            <Copy01Icon size={16} />
          </Button>
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onClick={handleDownload}
            aria-label="Download file"
            isDisabled={content === null}
          >
            <Download01Icon size={16} />
          </Button>
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onClick={closeSidebar}
            aria-label="Close preview"
          >
            <Cancel01Icon size={16} />
          </Button>
        </div>
      </div>

      <div
        className={`min-h-0 flex-1 ${isHtmlPreview ? "overflow-hidden" : "overflow-y-auto overscroll-contain"}`}
        onWheel={handleContentWheel}
      >
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner size="lg" />
          </div>
        ) : null}

        {error ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-red-400">Failed to load file</p>
          </div>
        ) : null}

        {!loading && !error && content !== null ? (
          <FileContentRenderer
            content={content}
            contentType={contentType}
            filename={filename}
            viewMode={viewMode}
          />
        ) : null}
      </div>
    </div>
  );
}
