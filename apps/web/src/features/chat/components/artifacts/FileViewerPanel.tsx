"use client";

import { Button } from "@heroui/button";
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
import { usePanelDrawsClose } from "@/components/layout/sidebar/RightSidebarSlot";
import { sessionFilesApi } from "@/features/chat/api/sessionFilesApi";
import {
  FileViewerBody,
  type ViewMode,
} from "@/features/chat/components/artifacts/FileViewerBody";
import { PREVIEWABLE_CONTENT_TYPES } from "@/features/chat/constants/files";
import { useArtifactText } from "@/features/chat/hooks/useArtifactText";
import { getExtension } from "@/features/chat/utils/fileExtension";
import { ShareLinkControls } from "@/features/short-links/components/ShareLinkControls";
import { sessionArtifactTargetId } from "@/features/short-links/utils/sessionArtifactTargetId";
import { copyWithFeedback } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import { useCloseRightSidebar } from "@/stores/layoutStore";

interface FileViewerPanelProps {
  conversationId: string;
  path: string;
  filename: string;
  contentType: string;
  sizeBytes?: number;
  inlineBody?: string;
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
  const isPdf = contentType === "application/pdf";
  const {
    text: content,
    loading,
    error,
  } = useArtifactText(conversationId, path, inlineBody, !isImage && !isPdf);
  const [copied, setCopied] = useState(false);
  const closeSidebar = useCloseRightSidebar();
  const drawsClose = usePanelDrawsClose();

  const isPreviewable = PREVIEWABLE_CONTENT_TYPES.has(contentType) || isImage;

  const [viewMode, setViewMode] = useState<ViewMode>(
    isPreviewable ? "preview" : "source",
  );

  useEffect(() => {
    setViewMode(isPreviewable ? "preview" : "source");
  }, [isPreviewable]);

  const handleCopy = useCallback(async () => {
    if (content === null) return;

    if (!(await copyWithFeedback(content))) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }, [content]);

  const handleDownload = useCallback(() => {
    const link = document.createElement("a");
    let objectUrl: string | null = null;
    if (isImage || content === null) {
      // For binary artifacts (images etc.) anchor to the auth-gated URL —
      // we never fetched the body and don't want to.
      link.href = sessionFilesApi.artifactUrl(conversationId, path);
    } else {
      const blob = new Blob([content], { type: contentType });
      objectUrl = URL.createObjectURL(blob);
      link.href = objectUrl;
    }
    link.download = filename;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    if (objectUrl) URL.revokeObjectURL(objectUrl);
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
      <div className="flex min-h-12 shrink-0 flex-wrap items-center gap-x-2 bg-zinc-800 px-2">
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

        <p
          className={cn(
            "min-w-0 truncate text-sm text-zinc-200",
            // Under sm the tabs and actions fill the row, so the name gets its own line.
            isPreviewable
              ? "order-last w-full flex-none pb-2 sm:order-none sm:w-auto sm:flex-1 sm:pb-0"
              : "flex-1",
          )}
        >
          {filename}
          <span className="text-zinc-500">{` · ${ext || "FILE"}${sizeLabel}`}</span>
        </p>

        <div className="ml-auto flex h-12 items-center gap-0.5">
          {copied ? (
            <span className="mr-1 text-xs text-emerald-400">Copied</span>
          ) : null}
          <ShareLinkControls
            iconOnly
            targetType="session_artifact"
            targetId={sessionArtifactTargetId(conversationId, path)}
          />
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
            isDisabled={!isImage && !isPdf && content === null}
          >
            <Download01Icon size={16} />
          </Button>
          {drawsClose && (
            <Button
              isIconOnly
              size="sm"
              variant="light"
              onClick={closeSidebar}
              aria-label="Close preview"
            >
              <Cancel01Icon size={16} />
            </Button>
          )}
        </div>
      </div>

      <div
        className={`min-h-0 flex-1 ${isHtmlPreview ? "overflow-hidden" : "overflow-y-auto overscroll-contain"}`}
        onWheel={handleContentWheel}
      >
        <FileViewerBody
          isImage={isImage}
          isPdf={isPdf}
          loading={loading}
          error={error}
          content={content}
          contentType={contentType}
          filename={filename}
          fileUrl={sessionFilesApi.artifactUrl(conversationId, path)}
          viewMode={viewMode}
        />
      </div>
    </div>
  );
}
