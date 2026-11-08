// @vitest-environment jsdom

/**
 * Regression: direct uploads (PR #859) dropped the conversation id, so the
 * server never mirrored the file into the session workspace and the executor
 * could not read it. The hook must send the id the browser is actually on.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useFileAttachments } from "@/features/chat/hooks/useFileAttachments";
import { useComposerStore } from "@/stores/composerStore";

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
});
