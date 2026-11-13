// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let search = "";
const replace = vi.fn();
const { sendMessage, toast } = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
  useRouter: () => ({ replace }),
  useParams: () => ({ id: "conv-1" }),
}));
vi.mock("@/i18n/navigation", () => ({ usePathname: () => "/c/conv-1" }));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock("@/features/chat/stream/sendMessage", () => ({ sendMessage }));
vi.mock("@/lib/toast", () => ({ toast }));

import { useOAuthSuccessToast } from "@/hooks/useOAuthSuccessToast";

function landOn(query: string): void {
  search = query;
  window.history.replaceState(null, "", `/c/conv-1?${query}`);
  renderHook(() => useOAuthSuccessToast());
}

describe("useOAuthSuccessToast account outcome", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("says an account already connected added nothing, and does not resume the chat", async () => {
    landOn(
      "oauth_success=true&integration=gmail&account_outcome=already_connected",
    );

    expect(toast.info).toHaveBeenCalledExactlyOnceWith(
      "That Gmail account was already connected, so nothing new was added.",
    );
    expect(toast.success).not.toHaveBeenCalled();
    await vi.dynamicImportSettled();
    expect(sendMessage).not.toHaveBeenCalled();
    expect(replace).toHaveBeenCalledWith("/c/conv-1", { scroll: false });
  });

  it("calls a signed-back-in account a reconnect and resumes the chat", async () => {
    landOn("oauth_success=true&integration=notion&account_outcome=reconnected");

    expect(toast.success).toHaveBeenCalledExactlyOnceWith("Reconnected Notion");
    await vi.waitFor(() =>
      expect(sendMessage).toHaveBeenCalledExactlyOnceWith(
        "Hey I just connected Notion",
        { conversationId: "conv-1" },
      ),
    );
  });
});
