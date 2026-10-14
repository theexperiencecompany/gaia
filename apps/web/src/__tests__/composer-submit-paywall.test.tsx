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
let isSubscriptionStatusUnknown = false;

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid, isUnknown: isSubscriptionStatusUnknown }),
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
  useComposerStore: (selector: (s: unknown) => unknown) =>
    selector({ workflowAutoSend: false }),
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
  useReplyToMessage: () => ({
    replyToMessage: null,
    clearReplyToMessage,
  }),
}));

import { useComposerSubmit } from "@/features/chat/hooks/useComposerSubmit";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

describe("useComposerSubmit paywall pre-check", () => {
  beforeEach(() => {
    isPaid = false;
    isSubscriptionStatusUnknown = false;
    useUpgradeModalStore.setState({ open: false, offer: null });
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
    expect(useUpgradeModalStore.getState().open).toBe(true);
    // Enforcement — the composer pre-check must never let the user dismiss
    // their way past the paywall.
    expect(useUpgradeModalStore.getState().dismissible).toBe(false);
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
    expect(useUpgradeModalStore.getState().open).toBe(false);
    expect(clearInputText).toHaveBeenCalledTimes(1);
  });

  it("lets the send proceed while the subscription status is still unknown, instead of opening the paywall (cold-cache race)", () => {
    isPaid = false;
    isSubscriptionStatusUnknown = true;
    const { result } = renderHook(() =>
      useComposerSubmit({
        inputRef: { current: null },
        scrollToBottom: vi.fn(),
      }),
    );

    result.current.handleFormSubmit();

    // The backend's 402 on chat-stream is the backstop for a genuinely free
    // user — a not-yet-resolved plan status must never trap a paying user
    // behind the non-dismissible paywall.
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(useUpgradeModalStore.getState().open).toBe(false);
  });
});
