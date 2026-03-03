"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { Copy01Icon, Download01Icon } from "@icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import { type VFSReadResponse, vfsApi } from "@/features/chat/api/vfsApi";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";

interface FileViewerPanelProps {
  path: string;
  filename: string;
  contentType: string;
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

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
  if (viewMode === "source") {
    const language = getLanguage(filename);
    return (
      <div className="rounded-lg bg-zinc-800 p-4">
        <MarkdownRenderer content={`\`\`\`${language}\n${content}\n\`\`\``} />
      </div>
    );
  }

  if (contentType === "text/markdown") {
    return (
      <div className="prose prose-invert max-w-none">
        <MarkdownRenderer content={content} />
      </div>
    );
  }

  if (contentType === "text/html") {
    return (
      <iframe
        title={filename}
        srcDoc={content}
        className="h-full w-full rounded-lg border border-zinc-700 bg-white"
        sandbox=""
        style={{ minHeight: "520px" }}
      />
    );
  }

  if (contentType === "text/x-latex") {
    return (
      <div className="prose prose-invert max-w-none">
        <MarkdownRenderer content={`$$\n${content}\n$$`} />
      </div>
    );
  }

  const language = getLanguage(filename);
  return (
    <div className="rounded-lg bg-zinc-800 p-4">
      <MarkdownRenderer content={`\`\`\`${language}\n${content}\n\`\`\``} />
    </div>
  );
}

export default function FileViewerPanel({
  path,
  filename,
  contentType,
}: FileViewerPanelProps) {
  const [fileData, setFileData] = useState<VFSReadResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const isPreviewable = useMemo(
    () => PREVIEWABLE_CONTENT_TYPES.has(contentType),
    [contentType],
  );

  const [viewMode, setViewMode] = useState<ViewMode>(
    isPreviewable ? "preview" : "source",
  );

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setError(null);

    vfsApi
      .readFile(path)
      .then((data) => {
        if (!cancelled) {
          setFileData(data);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message =
            err instanceof Error ? err.message : "Failed to load file";
          setError(message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [path]);

  const handleCopy = useCallback(async () => {
    if (!fileData) return;

    try {
      await navigator.clipboard.writeText(fileData.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // no-op
    }
  }, [fileData]);

  const handleDownload = useCallback(() => {
    if (!fileData) return;

    const blob = new Blob([fileData.content], { type: contentType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [fileData, filename, contentType]);

  const ext = getExtension(filename).toUpperCase();

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-700 px-4 py-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-white">
              {filename}
            </p>
            {fileData ? (
              <p className="text-xs text-zinc-400">
                {formatSize(fileData.size_bytes)}
              </p>
            ) : null}
          </div>

          <div className="flex items-center gap-1">
            <Button
              isIconOnly
              size="sm"
              variant="light"
              onClick={handleCopy}
              aria-label="Copy file"
            >
              <Copy01Icon size={16} />
            </Button>
            <Button
              isIconOnly
              size="sm"
              variant="light"
              onClick={handleDownload}
              aria-label="Download file"
            >
              <Download01Icon size={16} />
            </Button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Chip size="sm" variant="flat" className="text-xs">
            {ext || "FILE"}
          </Chip>

          {copied ? (
            <span className="text-xs text-emerald-400">Copied</span>
          ) : null}

          {isPreviewable ? (
            <div className="ml-auto flex rounded-md bg-zinc-800 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setViewMode("preview")}
                className={`rounded px-2 py-1 transition-colors ${
                  viewMode === "preview"
                    ? "bg-zinc-600 text-white"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                Preview
              </button>
              <button
                type="button"
                onClick={() => setViewMode("source")}
                className={`rounded px-2 py-1 transition-colors ${
                  viewMode === "source"
                    ? "bg-zinc-600 text-white"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                Code
              </button>
            </div>
          ) : null}
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner size="lg" />
          </div>
        ) : null}

        {error ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-red-400">{error}</p>
          </div>
        ) : null}

        {!loading && !error && fileData ? (
          <FileContentRenderer
            content={fileData.content}
            contentType={contentType}
            filename={filename}
            viewMode={viewMode}
          />
        ) : null}
      </div>
    </div>
  );
}
