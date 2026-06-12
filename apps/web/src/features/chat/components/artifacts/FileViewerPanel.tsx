"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { Tab, Tabs } from "@heroui/tabs";
import {
  Cancel01Icon,
  CodeIcon,
  Copy01Icon,
  Download01Icon,
  File01Icon,
} from "@icons";
import { formatFileSize } from "@shared/utils";
import { useCallback, useEffect, useState, type WheelEvent } from "react";
import { sessionFilesApi } from "@/features/chat/api/sessionFilesApi";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { useArtifactText } from "@/features/chat/hooks/useArtifactText";
import { useRightSidebar } from "@/stores/rightSidebarStore";

interface FileViewerPanelProps {
  conversationId: string;
  path: string;
  filename: string;
  contentType: string;
  sizeBytes?: number;
  inlineBody?: string;
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
    const previewDoc = buildHtmlPreviewDocument(content);

    return (
      <div className="h-full min-h-0">
        <iframe
          title={filename}
          srcDoc={previewDoc}
          className="block h-full w-full bg-white"
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

interface FileViewerBodyProps {
  isImage: boolean;
  loading: boolean;
  error: boolean;
  content: string | null;
  contentType: string;
  filename: string;
  conversationId: string;
  path: string;
  viewMode: ViewMode;
}

function FileViewerBody({
  isImage,
  loading,
  error,
  content,
  contentType,
  filename,
  conversationId,
  path,
  viewMode,
}: Readonly<FileViewerBodyProps>) {
  if (isImage) {
    return (
      <div className="flex h-full items-center justify-center bg-zinc-950 p-4">
        <img
          src={sessionFilesApi.artifactUrl(conversationId, path)}
          alt={filename}
          className="max-h-full max-w-full object-contain"
        />
      </div>
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

export default function FileViewerPanel({
  conversationId,
  path,
  filename,
  contentType,
  sizeBytes,
  inlineBody,
}: FileViewerPanelProps) {
  const isImage = contentType.startsWith("image/");
  const {
    text: content,
    loading,
    error,
  } = useArtifactText(conversationId, path, inlineBody, !isImage);
  const [copied, setCopied] = useState(false);
  const closeSidebar = useRightSidebar((state) => state.close);

  const isPreviewable = PREVIEWABLE_CONTENT_TYPES.has(contentType) || isImage;

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
    const link = document.createElement("a");
    if (isImage || content === null) {
      // For binary artifacts (images etc.) anchor to the auth-gated URL —
      // we never fetched the body and don't want to.
      link.href = sessionFilesApi.artifactUrl(conversationId, path);
    } else {
      const blob = new Blob([content], { type: contentType });
      link.href = URL.createObjectURL(blob);
    }
    link.download = filename;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    if (!isImage && content !== null) URL.revokeObjectURL(link.href);
  }, [content, contentType, conversationId, filename, isImage, path]);

  const ext = getExtension(filename).toUpperCase();
  const sizeLabel =
    sizeBytes === undefined ? "" : ` · ${formatFileSize(sizeBytes)}`;
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
    <div className="flex h-full min-h-0 flex-col bg-zinc-800">
      <div className="flex h-12 shrink-0 items-center gap-2 bg-zinc-800 px-2">
        {isPreviewable ? (
          <Tabs
            aria-label="View mode"
            selectedKey={viewMode}
            onSelectionChange={(key) => setViewMode(key as ViewMode)}
            size="sm"
            variant="solid"
          >
            <Tab
              key="preview"
              title={
                <div className="flex items-center gap-1.5">
                  <File01Icon size={14} />
                  <span>Preview</span>
                </div>
              }
            />
            <Tab
              key="source"
              title={
                <div className="flex items-center gap-1.5">
                  <CodeIcon size={14} />
                  <span>Code</span>
                </div>
              }
            />
          </Tabs>
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
            isDisabled={!isImage && content === null}
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
        <FileViewerBody
          isImage={isImage}
          loading={loading}
          error={error}
          content={content}
          contentType={contentType}
          filename={filename}
          conversationId={conversationId}
          path={path}
          viewMode={viewMode}
        />
      </div>
    </div>
  );
}
