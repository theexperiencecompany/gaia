import { useCallback } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import type { UploadedFilePreview } from "@/features/chat/components/files/FilePreview";
import {
  ALLOWED_FILE_TYPES,
  MAX_FILE_SIZE_BYTES,
  MAX_FILES,
  SUPPORTED_FILE_TYPES_LABEL,
} from "@/features/chat/constants/files";
import { currentConversationId } from "@/features/chat/utils/currentConversationId";
import { toast } from "@/lib/toast";
import { useComposerStore } from "@/stores/composerStore";

const validateFile = (file: File): string | null => {
  if (!ALLOWED_FILE_TYPES.includes(file.type)) {
    return `${file.name}: this file type isn't supported. ${SUPPORTED_FILE_TYPES_LABEL}.`;
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `${file.name}: exceeds the ${MAX_FILE_SIZE_BYTES / (1024 * 1024)}MB size limit`;
  }
  return null;
};

// Each uploading chip's request, so removing the chip can cancel it.
const inFlightUploads = new Map<string, AbortController>();

/**
 * Uploads files straight into the composer: each file appears as an
 * uploading chip immediately and resolves in place, no modal step.
 * Send stays blocked while any chip is uploading (useComposerIsUploading).
 */
export const useFileAttachments = () => {
  const attachFiles = useCallback(async (files: File[]) => {
    if (files.length === 0) return;

    const {
      uploadedFiles,
      addUploadedFile,
      replaceUploadedFile,
      removeUploadedFile,
      addUploadedFileData,
    } = useComposerStore.getState();

    // A pick over the limit keeps the files that fit instead of dropping the whole batch.
    const openSlots = Math.max(0, MAX_FILES - uploadedFiles.length);
    const fitting = files.slice(0, openSlots);
    if (fitting.length === 0) {
      toast.error(
        `Up to ${MAX_FILES} files per message. Remove one to attach another.`,
      );
      return;
    }
    if (fitting.length < files.length) {
      toast.error(
        `Up to ${MAX_FILES} files per message. Attached ${fitting.length}, skipped ${files.length - fitting.length}.`,
      );
    }

    const validFiles = fitting.filter((file) => {
      const error = validateFile(file);
      if (error) toast.error(error);
      return !error;
    });
    if (validFiles.length === 0) return;

    const pending: Array<{ file: File; tempId: string; previewUrl: string }> =
      [];
    // Every minted preview URL is tracked at creation so each one is
    // provably revoked once the batch settles.
    const previewObjectUrls: string[] = [];

    for (const file of validFiles) {
      const tempId = crypto.randomUUID();
      const previewUrl = file.type.startsWith("image/")
        ? URL.createObjectURL(file)
        : "";
      if (previewUrl) previewObjectUrls.push(previewUrl);
      pending.push({ file, tempId, previewUrl });
      addUploadedFile({
        id: tempId,
        url: previewUrl,
        name: file.name,
        type: file.type,
        size: file.size,
        isUploading: true,
      });
    }

    try {
      await Promise.allSettled(
        pending.map(async ({ file, tempId }) => {
          const upload = new AbortController();
          inFlightUploads.set(tempId, upload);
          try {
            const response = await chatApi.uploadFile(
              file,
              currentConversationId(),
              upload.signal,
            );
            const description = response.description || `File: ${file.name}`;
            const message = response.message || "File uploaded successfully";
            const uploaded: UploadedFilePreview = {
              id: response.fileId,
              url: response.url || "",
              name: file.name,
              type: file.type,
              size: file.size,
              description,
              message,
              isUploading: false,
            };
            const { uploadedFiles } = useComposerStore.getState();
            if (uploadedFiles.some((f) => f.id === tempId)) {
              replaceUploadedFile(tempId, uploaded);
              addUploadedFileData({
                fileId: response.fileId,
                url: response.url || "",
                filename: file.name,
                description,
                message,
                type: file.type,
                size: file.size,
              });
            } else {
              // The chip was removed after the server had stored the file.
              await chatApi.deleteFile(response.fileId);
            }
            return uploaded;
          } catch (error) {
            if (upload.signal.aborted) return undefined;
            // The API client already surfaced the backend detail (413/415…)
            // as a toast — just drop the failed chip.
            removeUploadedFile(tempId);
            throw error;
          } finally {
            inFlightUploads.delete(tempId);
          }
        }),
      );
    } finally {
      // Chips no longer need the previews: settled chips hold the server
      // URL (or nothing), failed chips are gone.
      for (const url of previewObjectUrls) {
        URL.revokeObjectURL(url);
      }
    }
  }, []);

  const removeAttachment = useCallback((chipId: string) => {
    inFlightUploads.get(chipId)?.abort();
    useComposerStore.getState().removeUploadedFile(chipId);
  }, []);

  return { attachFiles, removeAttachment };
};
