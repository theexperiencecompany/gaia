"use client";

import { Chip } from "@heroui/chip";

import { AttachmentIcon } from "@/icons";
import type { EmailPart } from "@/types/features/mailTypes";

interface EmailAttachmentsProps {
  parts: EmailPart[];
}

function flattenParts(parts: EmailPart[]): EmailPart[] {
  const result: EmailPart[] = [];
  for (const part of parts) {
    result.push(part);
    if (part.parts) {
      result.push(...flattenParts(part.parts));
    }
  }
  return result;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function EmailAttachments({ parts }: EmailAttachmentsProps) {
  const allParts = flattenParts(parts);
  const attachments = allParts.filter(
    (part) => part.filename && part.filename.length > 0,
  );

  if (attachments.length === 0) return null;

  return (
    <div className="mt-3 flex flex-col gap-2">
      <div className="flex items-center gap-1.5 text-xs text-gray-400">
        <AttachmentIcon className="h-3.5 w-3.5" />
        <span>
          {attachments.length} attachment
          {attachments.length > 1 ? "s" : ""}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {attachments.map((attachment) => (
          <Chip
            key={`${attachment.filename}-${attachment.body?.attachmentId ?? ""}`}
            size="sm"
            variant="bordered"
            color="default"
            startContent={
              <AttachmentIcon className="ml-1 h-3.5 w-3.5 text-gray-400" />
            }
          >
            <span className="text-xs text-gray-200">
              {attachment.filename}
            </span>
            {attachment.body?.size ? (
              <span className="ml-1 text-xs text-gray-500">
                ({formatFileSize(attachment.body.size)})
              </span>
            ) : null}
          </Chip>
        ))}
      </div>
    </div>
  );
}
