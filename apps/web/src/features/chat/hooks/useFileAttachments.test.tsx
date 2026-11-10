// @vitest-environment jsdom

/**
 * Regression: direct uploads (PR #859) dropped the conversation id, so the
 * server never mirrored the file into the session workspace and the executor
 * could not read it. The hook must send the id the browser is actually on.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MAX_FILES,
  SUPPORTED_FILE_TYPES_LABEL,
} from "@/features/chat/constants/files";
import { useFileAttachments } from "@/features/chat/hooks/useFileAttachments";
import { useComposerStore } from "@/stores/composerStore";
import { useActiveLoading } from "@/stores/streamStore";

const toastError = vi.fn();

vi.mock("@/lib/toast", () => ({
  toast: { error: (message: string) => toastError(message) },
}));

const uploadFile = vi.fn(async (_file: File, _conversationId?: string) => ({
  fileId: "file-1",
  url: "https://cdn.example/file-1.png",
  filename: "table.png",
  description: "a table",
  message: "File uploaded successfully",
}));

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: {
    uploadFile: (file: File, conversationId?: string) =>
      uploadFile(file, conversationId),
  },
}));

function png(): File {
  return new File([new Uint8Array([137, 80, 78, 71])], "table.png", {
    type: "image/png",
  });
}

describe("useFileAttachments", () => {
  beforeEach(() => {
    uploadFile.mockClear();
    toastError.mockClear();
    useComposerStore.setState({ uploadedFiles: [] });
    // jsdom has no object-URL implementation; the hook only mints previews.
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:preview"),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the conversation id the browser is on", async () => {
    window.history.replaceState({}, "", "/en/c/conv-123");
    const { result } = renderHook(() => useFileAttachments());

    await act(async () => {
      await result.current.attachFiles([png()]);
    });

    expect(uploadFile).toHaveBeenCalledWith(expect.any(File), "conv-123");
  });

  it("omits the id on a new chat, where the server seeds it on the first turn", async () => {
    window.history.replaceState({}, "", "/");
    const { result } = renderHook(() => useFileAttachments());

    await act(async () => {
      await result.current.attachFiles([png()]);
    });

    expect(uploadFile).toHaveBeenCalledWith(expect.any(File), undefined);
  });

  it("attaches the files that fit when a pick exceeds the per-message limit", async () => {
    useComposerStore.setState({
      uploadedFiles: [1, 2, 3].map((n) => ({
        id: `existing-${n}`,
        url: "",
        name: `existing-${n}.png`,
        type: "image/png",
        size: 4,
        isUploading: false,
      })),
    });
    const { result } = renderHook(() => useFileAttachments());

    await act(async () => {
      await result.current.attachFiles([png(), png(), png(), png()]);
    });

    expect(uploadFile).toHaveBeenCalledTimes(MAX_FILES - 3);
    expect(toastError).toHaveBeenCalledWith(
      `Up to ${MAX_FILES} files per message. Attached 2, skipped 2.`,
    );
  });

  it("names the supported types when a file type is rejected", async () => {
    const { result } = renderHook(() => useFileAttachments());
    const zip = new File([new Uint8Array([80, 75, 3, 4])], "photos.zip", {
      type: "application/zip",
    });

    await act(async () => {
      await result.current.attachFiles([zip]);
    });

    expect(uploadFile).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledWith(
      `photos.zip: this file type isn't supported. ${SUPPORTED_FILE_TYPES_LABEL}.`,
    );
  });
  // Regression: an upload set the stream store's aux loading, so GAIA's thinking
  // line read "Uploading files..." for the user's own action.
  it("keeps an upload on the user's chip and off GAIA's loading indicator", async () => {
    let finishUpload: () => void = () => undefined;
    uploadFile.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishUpload = () =>
            resolve({
              fileId: "file-1",
              url: "https://cdn.example/file-1.png",
              filename: "table.png",
              description: "a table",
              message: "File uploaded successfully",
            });
        }),
    );
    const { result } = renderHook(() => ({
      attachments: useFileAttachments(),
      loading: useActiveLoading(),
    }));

    let attaching: Promise<void> = Promise.resolve();
    act(() => {
      attaching = result.current.attachments.attachFiles([png()]);
    });

    await waitFor(() =>
      expect(useComposerStore.getState().uploadedFiles[0]?.isUploading).toBe(
        true,
      ),
    );
    expect(result.current.loading.isLoading).toBe(false);

    await act(async () => {
      finishUpload();
      await attaching;
    });
    expect(useComposerStore.getState().uploadedFiles[0]?.isUploading).toBe(
      false,
    );
    expect(result.current.loading.isLoading).toBe(false);
  });
});
