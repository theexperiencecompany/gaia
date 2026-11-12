"use client";

import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import { Spinner } from "@heroui/spinner";
import { Download01Icon, File01Icon, LinkSquare02Icon } from "@icons";
import { formatFileSize } from "@shared/utils";
import Image from "next/image";

import { FileViewerBody } from "@/features/chat/components/artifacts/FileViewerBody";
import { PREVIEWABLE_CONTENT_TYPES } from "@/features/chat/constants/files";
import type {
  LinkContent,
  PublicSessionArtifact,
} from "@/types/features/shortLinkTypes";

import { linkDownloadUrl } from "../api/linkViewerApi";
import { ACTIVE_CONTENT_SANDBOX } from "../constants";
import { useLinkContentUrl } from "../hooks/useLinkContentUrl";
import type { LinkViewProps } from "../types";

// A shared file's HTML is shown as its source, never as a srcDoc frame on this
// origin: active HTML runs only from the isolated content origin.
const HTML_CONTENT_TYPE = "text/html";

const FRAME_CLASS = "block h-[75dvh] w-full bg-white";

function FramedContent({
  slug,
  filename,
  content,
}: {
  slug: string;
  filename: string;
  content: LinkContent;
}) {
  const { url, failed, onLoad, onError } = useLinkContentUrl(slug);

  if (failed) return <MetadataCard message="This file couldn't be loaded." />;
  if (!url) {
    return (
      <div className="flex h-[75dvh] items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }

  switch (content.render) {
    case "frame_active":
      return (
        <iframe
          title={filename}
          src={url}
          sandbox={ACTIVE_CONTENT_SANDBOX}
          referrerPolicy="no-referrer"
          allow=""
          loading="lazy"
          className={FRAME_CLASS}
          onLoad={onLoad}
          onError={onError}
        />
      );
    case "image":
    case "image_svg":
      return (
        <div className="flex items-center justify-center bg-zinc-950 p-4">
          <Image
            src={url}
            alt={filename}
            width={1200}
            height={900}
            unoptimized
            referrerPolicy="no-referrer"
            className="h-auto max-h-[75dvh] w-auto max-w-full object-contain"
            onLoad={onLoad}
            onError={onError}
          />
        </div>
      );
    case "media":
      return content.mime.startsWith("audio/") ? (
        <div className="p-4">
          <audio
            src={url}
            controls
            className="w-full"
            onLoadedData={onLoad}
            onError={onError}
          >
            <track kind="captions" />
          </audio>
        </div>
      ) : (
        <video
          src={url}
          controls
          className="max-h-[75dvh] w-full bg-black"
          onLoadedData={onLoad}
          onError={onError}
        >
          <track kind="captions" />
        </video>
      );
    case "pdf":
      // Browsers refuse to render a PDF in a sandboxed frame; the content origin isolates it.
      return (
        <div className="flex flex-col">
          <div className="flex justify-end p-2">
            <Button
              as={Link}
              href={url}
              referrerPolicy="no-referrer"
              size="sm"
              variant="flat"
              startContent={<LinkSquare02Icon className="size-4" />}
            >
              Open
            </Button>
          </div>
          <iframe
            title={filename}
            src={url}
            referrerPolicy="no-referrer"
            className={FRAME_CLASS}
            onLoad={onLoad}
            onError={onError}
          />
        </div>
      );
    default:
      return <MetadataCard message={CANNOT_PREVIEW} />;
  }
}

const CANNOT_PREVIEW =
  "This file can't be previewed here. Download it to open it.";

function MetadataCard({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center gap-2 p-10 text-center">
      <File01Icon size={24} className="text-zinc-500" />
      <p className="text-sm text-zinc-400">{message}</p>
    </div>
  );
}

function TextContent({ view }: { view: PublicSessionArtifact }) {
  const preview =
    view.content_type !== HTML_CONTENT_TYPE &&
    PREVIEWABLE_CONTENT_TYPES.has(view.content_type);
  return (
    <div className="py-2">
      <FileViewerBody
        isImage={false}
        isPdf={false}
        loading={false}
        error={false}
        content={view.text}
        contentType={view.content_type}
        filename={view.filename}
        fileUrl=""
        viewMode={preview ? "preview" : "source"}
      />
    </div>
  );
}

/**
 * A shared file under a fixed GAIA bar the file cannot cover: framed from the
 * content origin by its render mode, shown as text when the page renders it
 * itself, or described when it can only be downloaded.
 */
export function PublicSessionArtifactView({
  slug,
  view,
  content,
  reportAction,
}: LinkViewProps<"session_artifact">) {
  return (
    <article className="flex flex-col gap-3">
      <header className="sticky top-0 z-10 flex items-center justify-between gap-4 rounded-2xl bg-zinc-800 px-4 py-3">
        <div className="min-w-0">
          <h1 className="truncate text-base font-medium text-white">
            {view.filename}
          </h1>
          <p className="flex gap-2 text-xs text-zinc-500">
            <span>{formatFileSize(view.size_bytes)}</span>
            <span>Made with GAIA</span>
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {reportAction}
          <Button
            as={Link}
            href={linkDownloadUrl(slug)}
            referrerPolicy="no-referrer"
            size="sm"
            variant="flat"
            startContent={<Download01Icon className="size-4" />}
          >
            Download
          </Button>
        </div>
      </header>
      <div className="overflow-hidden rounded-2xl bg-zinc-800">
        {content ? (
          <FramedContent
            slug={slug}
            filename={view.filename}
            content={content}
          />
        ) : view.text !== null ? (
          <TextContent view={view} />
        ) : (
          <MetadataCard message={CANNOT_PREVIEW} />
        )}
      </div>
    </article>
  );
}
