import { useCallback, useRef } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import type { UploadedFilePreview } from "@/features/chat/components/files/FilePreview";
import {
  ALLOWED_FILE_TYPES,
  MAX_FILE_SIZE_BYTES,
  MAX_FILES,
} from "@/features/chat/constants/files";
import { toast } from "@/lib/toast";
import { useComposerStore } from "@/stores/composerStore";
import { useStreamStore } from "@/stores/streamStore";

const validateFile = (file: File): string | null => {
  if (!ALLOWED_FILE_TYPES.includes(file.type)) {
    return `${file.name}: file type not supported`;
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `${file.name}: exceeds the ${MAX_FILE_SIZE_BYTES / (1024 * 1024)}MB size limit`;
  }
  return null;
};

/**
 * Uploads files straight into the composer: each file appears as an
 * uploading chip immediately and resolves in place, no modal step.
 * Send stays blocked while any chip is uploading (useComposerIsUploading).
 */
export const useFileAttachments = () => {
  const setAuxLoading = useStreamStore((state) => state.setAuxLoading);
  // Ref-count concurrent attachFiles invocations so a slow batch doesn't clear
  // the global loading state while a later batch is still uploading.
  const activeUploads = useRef(0);

  const attachFiles = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;

      const {
        uploadedFiles,
        addUploadedFile,
        replaceUploadedFile,
        removeUploadedFile,
        addUploadedFileData,
      } = useComposerStore.getState();

      if (uploadedFiles.length + files.length > MAX_FILES) {
        toast.error(`You can attach a maximum of ${MAX_FILES} files`);
        return;
      }

      const validFiles = files.filter((file) => {
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

      activeUploads.current += 1;
      setAuxLoading(true, "Uploading files...");
      try {
        await Promise.allSettled(
          pending.map(async ({ file, tempId }) => {
            try {
              const response = await chatApi.uploadFile(file);
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
              }
              return uploaded;
            } catch (error) {
              // apiService already surfaced the backend detail (413/415…)
              // as a toast — just drop the failed chip.
              removeUploadedFile(tempId);
              throw error;
            }
          }),
        );
      } finally {
        // Chips no longer need the previews: settled chips hold the server
        // URL (or nothing), failed chips are gone.
        for (const url of previewObjectUrls) {
          URL.revokeObjectURL(url);
        }
        activeUploads.current -= 1;
        if (activeUploads.current === 0) setAuxLoading(false);
      }
    },
    [setAuxLoading],
  );

  return { attachFiles };
};
