// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sendMessage = vi.fn();
const clearInputText = vi.fn();
const clearAllFiles = vi.fn();
const clearToolSelection = vi.fn();
const clearSelectedWorkflow = vi.fn();
const clearSelectedCalendarEvent = vi.fn();
const clearReplyToMessage = vi.fn();

let isPaid = false;
let isSubscriptionStatusLoading = false;

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid, isLoading: isSubscriptionStatusLoading }),
}));

vi.mock("@/hooks/useSendMessage", () => ({
  useSendMessage: () => sendMessage,
}));

vi.mock("@/features/chat/hooks/useCalendarEventSelection", () => ({
  useCalendarEventSelection: () => ({
    selectedCalendarEvent: null,
    clearSelectedCalendarEvent,
  }),
}));

vi.mock("@/features/chat/hooks/useWorkflowSelection", () => ({
  useWorkflowSelection: () => ({
    selectedWorkflow: null,
    clearSelectedWorkflow,
  }),
}));

vi.mock("@/stores/composerStore", () => ({
  useInputText: () => "Hello GAIA",
  useComposerTextActions: () => ({ clearInputText }),
  useComposerModeSelection: () => ({
    selectedTool: null,
    selectedToolCategory: null,
    setSelectedTool: vi.fn(),
    setSelectedToolCategory: vi.fn(),
    clearToolSelection,
  }),
  useComposerFiles: () => ({
    uploadedFiles: [],
    uploadedFileData: [],
    clearAllFiles,
  }),
  useComposerIsUploading: () => false,
  useComposerUI: () => ({ isSlashCommandDropdownOpen: false }),
}));

vi.mock("@/stores/replyToMessageStore", () => ({
  useReplyToMessage: () => ({
    replyToMessage: null,
    clearReplyToMessage,
  }),
}));

vi.mock("@/stores/workflowSelectionStore", () => ({
  useWorkflowSelectionStore: () => ({ autoSend: false }),
}));

import { useComposerSubmit } from "@/features/chat/hooks/useComposerSubmit";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

describe("useComposerSubmit paywall pre-check", () => {
  beforeEach(() => {
    isPaid = false;
    isSubscriptionStatusLoading = false;
    usePaywallModalStore.setState({ open: false, offer: null });
    vi.clearAllMocks();
  });

  it("opens the paywall and does not send for a free user", () => {
    isPaid = false;
    const { result } = renderHook(() =>
      useComposerSubmit({
        inputRef: { current: null },
        scrollToBottom: vi.fn(),
      }),
    );

    result.current.handleFormSubmit();

    expect(sendMessage).not.toHaveBeenCalled();
    expect(usePaywallModalStore.getState().open).toBe(true);
    // Composer input is left intact — free users can keep typing.
    expect(clearInputText).not.toHaveBeenCalled();
  });

  it("sends the message for a paid user and does not open the paywall", () => {
    isPaid = true;
    const { result } = renderHook(() =>
      useComposerSubmit({
        inputRef: { current: null },
        scrollToBottom: vi.fn(),
      }),
    );

    result.current.handleFormSubmit();

    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(usePaywallModalStore.getState().open).toBe(false);
    expect(clearInputText).toHaveBeenCalledTimes(1);
  });

  it("lets the send proceed while the subscription-status query is still loading, instead of opening the paywall (cold-cache race)", () => {
    isPaid = false;
    isSubscriptionStatusLoading = true;
    const { result } = renderHook(() =>
      useComposerSubmit({
        inputRef: { current: null },
        scrollToBottom: vi.fn(),
      }),
    );

    result.current.handleFormSubmit();

    // The backend's 402 on chat-stream is the backstop for a genuinely free
    // user — a not-yet-resolved query must never trap a paying user behind
    // the non-dismissible paywall.
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(usePaywallModalStore.getState().open).toBe(false);
  });
});
