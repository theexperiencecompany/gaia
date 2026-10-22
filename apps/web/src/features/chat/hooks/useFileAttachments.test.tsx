// @vitest-environment jsdom

/**
 * Regression: an upload set the stream store's aux loading, so GAIA's thinking
 * line read "Uploading files..." for the user's own action.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { chatApi } from "@/features/chat/api/chatApi";
import { useFileAttachments } from "@/features/chat/hooks/useFileAttachments";
import { useComposerStore } from "@/stores/composerStore";
import { useActiveLoading } from "@/stores/streamStore";

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: { uploadFile: vi.fn() },
}));

const uploadFile = vi.mocked(chatApi.uploadFile);

describe("useFileAttachments", () => {
  afterEach(() => {
    useComposerStore.getState().resetComposer();
    uploadFile.mockReset();
  });

  it("keeps an upload on the user's chip and off GAIA's loading indicator", async () => {
    let finishUpload: () => void = () => undefined;
    uploadFile.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishUpload = () =>
            resolve({
              fileId: "file-1",
              url: "https://files.example/notes.md",
              filename: "notes.md",
              type: "text/markdown",
            });
        }),
    );
    const { result } = renderHook(() => ({
      attachments: useFileAttachments(),
      loading: useActiveLoading(),
    }));

    let attaching: Promise<void> = Promise.resolve();
    act(() => {
      attaching = result.current.attachments.attachFiles([
        new File(["# notes"], "notes.md", { type: "text/markdown" }),
      ]);
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
