"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { Cancel01Icon } from "@icons";
import { formatFileSize } from "@shared/utils";
import Image from "next/image";
import type { ReactNode } from "react";
import { useState } from "react";

import { FileTypeIcon } from "@/features/chat/components/files/FileTypeIcon";
import {
  getFileTypeExtension,
  getFormattedFileType,
} from "@/features/chat/components/files/fileTypeConfig";
import { cn } from "@/lib/utils";

const ICON_SIZE = 36;

/**
 * The surface the card sits on. Depth comes from one layer up: on the chat
 * page that is zinc-800, inside the zinc-800 composer it is zinc-700.
 */
const SURFACE_CLASSES = {
  page: "bg-zinc-800 hover:bg-zinc-700/70",
  composer: "bg-zinc-700 hover:bg-zinc-600/60",
} as const;

export type FileCardSurface = keyof typeof SURFACE_CLASSES;

export interface FileCardProps {
  name: string;
  /** MIME type when known; the extension of `name` is the fallback. */
  mimeType?: string;
  sizeBytes?: number;
  /** Shown in place of the type icon (composer image uploads). */
  thumbnailUrl?: string;
  surface?: FileCardSurface;
  isUploading?: boolean;
  onPress?: () => void;
  onRemove?: () => void;
  /** Secondary actions (download, share), shown on hover, focus and touch screens. */
  actions?: ReactNode;
}

/** One file, everywhere: composer uploads, user attachments and the files GAIA makes. */
export function FileCard({
  name,
  mimeType = "",
  sizeBytes,
  thumbnailUrl,
  surface = "page",
  isUploading = false,
  onPress,
  onRemove,
  actions,
}: FileCardProps) {
  const [isHovered, setIsHovered] = useState(false);
  const extension = getFileTypeExtension(mimeType, name);
  const sizeLabel =
    sizeBytes !== undefined
      ? formatFileSize(sizeBytes)
      : getFormattedFileType(mimeType, name);
  const meta = isUploading ? "Uploading" : sizeLabel;

  const body = (
    <>
      {isUploading ? (
        <span className="flex size-9 shrink-0 items-center justify-center">
          <Spinner size="sm" variant="simple" />
        </span>
      ) : thumbnailUrl ? (
        <Image
          src={thumbnailUrl}
          alt={name}
          width={ICON_SIZE}
          height={ICON_SIZE}
          className="size-9 shrink-0 rounded-lg object-cover outline outline-1 -outline-offset-1 outline-white/10"
        />
      ) : (
        <FileTypeIcon
          extension={extension}
          size={ICON_SIZE}
          isHovered={isHovered}
        />
      )}
      <span className="flex min-w-0 flex-1 flex-col text-left">
        <span className="truncate text-sm font-medium text-zinc-100">
          {name}
        </span>
        <span
          className={cn(
            "text-xs text-zinc-400 tabular-nums",
            onPress && "group-hover/file:hidden",
          )}
        >
          {meta}
        </span>
        {onPress && (
          <span className="hidden text-xs text-zinc-500 group-hover/file:inline">
            Click to open
          </span>
        )}
      </span>
    </>
  );

  return (
    <div
      className={cn(
        "group/file relative flex w-64 max-w-full items-center rounded-2xl transition-colors",
        SURFACE_CLASSES[surface],
      )}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {onPress ? (
        <Button
          disableRipple
          variant="light"
          aria-label={`Open ${name}`}
          // A click opens the viewer without pulling focus off the composer input.
          preventFocusOnPress
          onPress={onPress}
          className="h-auto min-w-0 flex-1 justify-start gap-2.5 rounded-2xl bg-transparent p-2 pr-3 data-[hover=true]:bg-transparent"
        >
          {body}
        </Button>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-2.5 p-2 pr-3">
          {body}
        </div>
      )}

      {actions && (
        <div className="hidden shrink-0 items-center pr-1.5 group-hover/file:flex group-focus-within/file:flex pointer-coarse:flex">
          {actions}
        </div>
      )}

      {onRemove && (
        <Button
          isIconOnly
          size="sm"
          variant="faded"
          radius="full"
          aria-label={`Remove ${name}`}
          isDisabled={isUploading}
          onPress={onRemove}
          className="absolute -top-1.5 -right-1.5 z-10 h-6 w-6 min-w-0 opacity-0 transition-opacity group-hover/file:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
        >
          <Cancel01Icon size={12} />
        </Button>
      )}
    </div>
  );
}
