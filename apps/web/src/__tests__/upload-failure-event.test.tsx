// @vitest-environment jsdom
import { ApiError } from "@shared/api";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const uploadFile = vi.fn();
const trackEvent = vi.fn();

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: { uploadFile: (...args: unknown[]) => uploadFile(...args) },
}));
vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { CHAT_FILE_UPLOAD_FAILED: "chat:file_upload_failed" },
  trackEvent: (...args: unknown[]) => trackEvent(...args),
}));
vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { useFileAttachments } from "@/features/chat/hooks/useFileAttachments";

describe("upload failure capture", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("captures status, size and type when an upload gets no response", async () => {
    uploadFile.mockRejectedValue(new ApiError("Network Error", 0));
    const file = new File([new Uint8Array(2_000_000)], "notes.pdf", {
      type: "application/pdf",
    });
    const { result } = renderHook(() => useFileAttachments());

    await act(() => result.current.attachFiles([file]));

    expect(trackEvent).toHaveBeenCalledWith("chat:file_upload_failed", {
      status: 0,
      size_bytes: 2_000_000,
      content_type: "application/pdf",
    });
  });

  it("captures nothing when the upload succeeds", async () => {
    uploadFile.mockResolvedValue({ fileId: "f1", url: "u" });
    const file = new File(["hi"], "a.txt", { type: "text/plain" });
    const { result } = renderHook(() => useFileAttachments());

    await act(() => result.current.attachFiles([file]));

    expect(trackEvent).not.toHaveBeenCalled();
  });
});
