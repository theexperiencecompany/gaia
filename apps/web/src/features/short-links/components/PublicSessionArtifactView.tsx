"use client";

import { Button } from "@heroui/button";
import { Download01Icon, File01Icon } from "@icons";
import { formatFileSize } from "@shared/utils";

import { FileViewerBody } from "@/features/chat/components/artifacts/FileViewerBody";
import { PREVIEWABLE_CONTENT_TYPES } from "@/features/chat/constants/files";
import { shortLinkFileUrl } from "@/features/short-links/api/shortLinksApi";
import type { PublicSessionArtifact } from "@/types/features/shortLinkTypes";

// Frames (HTML preview, PDF viewer, images) need a definite height to fill.
const FRAMED_CONTENT_TYPES = new Set(["text/html", "application/pdf"]);

interface PublicSessionArtifactViewProps {
  slug: string;
  view: PublicSessionArtifact;
}

export function PublicSessionArtifactView({
  slug,
  view,
}: PublicSessionArtifactViewProps) {
  const fileUrl = shortLinkFileUrl(slug);
  const isImage = view.content_type.startsWith("image/");
  const isPdf = view.content_type === "application/pdf";
  const canRender = isImage || isPdf || view.content !== null;
  const isFramed = isImage || FRAMED_CONTENT_TYPES.has(view.content_type);

  return (
    <article className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-medium text-white">
            {view.filename}
          </h1>
          <p className="text-sm text-zinc-500">
            {formatFileSize(view.size_bytes)}
          </p>
        </div>
        <Button
          as="a"
          href={fileUrl}
          download={view.filename}
          variant="flat"
          size="sm"
          startContent={<Download01Icon size={16} />}
        >
          Download
        </Button>
      </div>

      {canRender ? (
        <div
          className={`overflow-hidden rounded-2xl bg-zinc-800 ${isFramed ? "h-[75dvh]" : "py-2"}`}
        >
          <FileViewerBody
            isImage={isImage}
            isPdf={isPdf}
            loading={false}
            error={false}
            content={view.content}
            contentType={view.content_type}
            filename={view.filename}
            fileUrl={fileUrl}
            viewMode={
              PREVIEWABLE_CONTENT_TYPES.has(view.content_type)
                ? "preview"
                : "source"
            }
          />
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2 rounded-2xl bg-zinc-800 p-10 text-center">
          <File01Icon size={24} className="text-zinc-500" />
          <p className="text-sm text-zinc-400">
            This file can't be previewed here. Download it to open it.
          </p>
        </div>
      )}
    </article>
  );
}
