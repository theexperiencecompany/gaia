// @vitest-environment jsdom
//
// Regression coverage for the "paying user sees free-tier UI on reload" bug,
// specifically the voice-mode gate in ChatPage's MainChat: it used to read
// `subscriptionStatus?.is_subscribed` directly from the raw (possibly
// disabled/never-fetched) subscription-status query, so a cold cache read
// as "not subscribed" and a paying user got the upgrade paywall instead of
// entering voice mode. The fix routes through `useIsPaid()` and its
// `isUnknown` flag: never treat "unknown" as "not paid".
import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let isPaid = false;
let isUnknown = false;

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid, isUnknown }),
}));

const openPricingModal = vi.fn();
const openPaywallModal = vi.fn();
const enterVoiceMode = vi.fn();
const exitVoiceMode = vi.fn();
const prefetchConnectionDetails = vi.fn();
const trackEvent = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/components/ui/message-scroller", () => ({
  MessageScrollerProvider: ({ children }: { children: React.ReactNode }) =>
    children,
  useMessageScroller: () => ({ scrollToEnd: vi.fn() }),
}));

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: { markAsRead: vi.fn().mockResolvedValue(undefined) },
}));

vi.mock("@/features/chat/components/composer/Composer", () => ({
  default: () => null,
}));

vi.mock("@/features/chat/components/files/FileDropModal", () => ({
  FileDropModal: () => null,
}));

vi.mock(
  "@/features/chat/components/interface/founder-letter/FounderLetter",
  () => ({
    FounderLetter: () => null,
  }),
);

vi.mock("@/features/chat/components/interface/hooks/useChatLayout", () => ({
  useChatLayout: () => ({
    hasMessages: false,
    chatRef: { current: null },
    dummySectionRef: { current: null },
    inputRef: { current: null },
    fileUploadRef: { current: null },
    convoIdParam: null,
  }),
}));

vi.mock(
  "@/features/chat/components/interface/layouts/ChatWithMessages",
  () => ({
    ChatWithMessages: () => null,
  }),
);

// Captures the composerProps built inside MainChat so the test can invoke
// the voice-mode gate handlers directly, exactly as Composer/NewChatLayout
// would via a click/hover.
let capturedComposerProps: {
  onVoiceModeHover: () => void;
  voiceModeActive: () => void;
} | null = null;

vi.mock("@/features/chat/components/interface/layouts/NewChatLayout", () => ({
  NewChatLayout: ({
    composerProps,
  }: {
    composerProps: {
      onVoiceModeHover: () => void;
      voiceModeActive: () => void;
    };
  }) => {
    capturedComposerProps = composerProps;
    return null;
  },
}));

vi.mock(
  "@/features/chat/components/voice-agent/hooks/useConnectionDetails",
  () => ({
    usePrefetchConnectionDetails: () => prefetchConnectionDetails,
  }),
);

vi.mock(
  "@/features/chat/components/voice-agent/VoiceControlBarContainer",
  () => ({
    VoiceControlBarContainer: ({ children }: { children: React.ReactNode }) =>
      children,
    VoiceControlBarSlot: () => null,
  }),
);

vi.mock("@/features/chat/components/voice-agent/VoiceModeBackground", () => ({
  VoiceModeBackground: () => null,
}));

vi.mock("@/features/chat/hooks/useStreamResume", () => ({
  // Reload-mid-stream recovery — irrelevant to the voice-mode gate under test.
  useStreamResume: () => undefined,
}));

vi.mock("@/features/integrations/hooks/useIntegrations", () => ({
  // Refreshes the integrations catalog — irrelevant to the voice-mode gate.
  useIntegrations: () => undefined,
}));

vi.mock("@/hooks/ui/useDragAndDrop", () => ({
  useDragAndDrop: () => ({ isDragging: false, dragHandlers: {} }),
}));

const sendMessage = vi.fn();
vi.mock("@/hooks/useSendMessage", () => ({
  useSendMessage: () => sendMessage,
}));

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { CHAT_VOICE_MODE_TOGGLED: "chat:voice_mode_toggled" },
  trackEvent: (...args: unknown[]) => trackEvent(...args),
}));

vi.mock("@/lib/db/chatDb", () => ({
  db: { updateConversationFields: vi.fn() },
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}));

vi.mock("@/services/syncService", () => ({
  syncSingleConversation: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/stores/chatStore", () => ({
  useChatStore: Object.assign(
    (selector: (s: unknown) => unknown) =>
      selector({ setActiveConversationId: vi.fn() }),
    {
      getState: () => ({
        conversations: [],
        activeConversationId: null,
        clearOptimisticMessage: vi.fn(),
      }),
    },
  ),
}));

let pendingPrompt: string | null = null;
let pendingPromptAutoSend = false;
const clearPendingPrompt = vi.fn(() => {
  pendingPrompt = null;
  pendingPromptAutoSend = false;
});

vi.mock("@/stores/composerStore", () => ({
  useComposerTextActions: () => ({ clearPendingPrompt }),
  usePendingPrompt: () => pendingPrompt,
  usePendingPromptAutoSend: () => pendingPromptAutoSend,
}));

vi.mock("@/stores/paywallModalStore", () => ({
  usePaywallModalStore: (selector: (s: unknown) => unknown) =>
    selector({ openModal: openPaywallModal }),
}));

vi.mock("@/stores/pricingModalStore", () => ({
  usePricingModalStore: (selector: (s: unknown) => unknown) =>
    selector({ openModal: openPricingModal }),
}));

vi.mock("@/stores/voiceModeStore", () => ({
  useDiscoveredConversationId: () => null,
  useVoiceModeActions: () => ({ enterVoiceMode, exitVoiceMode }),
  useVoiceModeActive: () => false,
}));

vi.mock("@/stores/workflowSelectionStore", () => ({
  useWorkflowSelectionStore: Object.assign(
    (selector: (s: unknown) => unknown) =>
      selector({ selectedWorkflow: null, autoSend: false }),
    { getState: () => ({ clearSelectedWorkflow: vi.fn() }) },
  ),
}));

import ChatPage from "@/features/chat/components/interface/ChatPage";

describe("ChatPage voice-mode gate — plan status unknown vs. known-free", () => {
  beforeEach(() => {
    isPaid = false;
    isUnknown = false;
    capturedComposerProps = null;
    openPricingModal.mockReset();
    openPaywallModal.mockReset();
    enterVoiceMode.mockReset();
    prefetchConnectionDetails.mockReset();
    trackEvent.mockReset();
  });

  it("opens the pricing modal instead of entering voice mode for a known-free user", () => {
    isPaid = false;
    isUnknown = false;
    render(<ChatPage />);

    act(() => capturedComposerProps?.voiceModeActive());

    expect(openPricingModal).toHaveBeenCalledTimes(1);
    expect(enterVoiceMode).not.toHaveBeenCalled();
  });

  it("enters voice mode for a paid user", () => {
    isPaid = true;
    isUnknown = false;
    render(<ChatPage />);

    act(() => capturedComposerProps?.voiceModeActive());

    expect(openPricingModal).not.toHaveBeenCalled();
    expect(enterVoiceMode).toHaveBeenCalledTimes(1);
  });

  it("lets voice mode proceed (does not paywall) while the subscription status is still unknown", () => {
    isPaid = false;
    isUnknown = true;
    render(<ChatPage />);

    act(() => capturedComposerProps?.voiceModeActive());

    // The critical assertion: before the fix, this read `subscriptionStatus
    // ?.is_subscribed` directly off the raw (disabled/never-fetched) query,
    // which is `undefined` in this exact window — falsy, so a paying user
    // reloading mid-fetch got the upgrade paywall instead of their call.
    expect(openPricingModal).not.toHaveBeenCalled();
    expect(enterVoiceMode).toHaveBeenCalledTimes(1);
  });

  it("does not warm the voice session token on hover while the subscription status is still unknown", () => {
    isPaid = false;
    isUnknown = true;
    render(<ChatPage />);

    act(() => capturedComposerProps?.onVoiceModeHover());

    expect(prefetchConnectionDetails).not.toHaveBeenCalled();
  });

  it("warms the voice session token on hover for a paid user", () => {
    isPaid = true;
    isUnknown = false;
    render(<ChatPage />);

    act(() => capturedComposerProps?.onVoiceModeHover());

    expect(prefetchConnectionDetails).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Onboarding's web first message. Mounted here rather than in a file of its own
// because ChatPage is the component under test in both cases and its mock
// preamble above is the only harness that boots it.
// ---------------------------------------------------------------------------

describe("ChatPage pending-prompt auto-send", () => {
  beforeEach(() => {
    isPaid = true;
    isUnknown = false;
    pendingPrompt = null;
    pendingPromptAutoSend = false;
    sendMessage.mockReset();
    clearPendingPrompt.mockClear();
  });

  it("sends a flagged prompt as the user's turn into a new conversation", () => {
    pendingPrompt = "Hi! I'm a founder. Who are you?";
    pendingPromptAutoSend = true;

    render(<ChatPage />);

    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith(
      "Hi! I'm a founder. Who are you?",
      {
        selectedTool: null,
        selectedToolCategory: null,
        // null forces a brand-new conversation rather than appending to whatever
        // the store last had open.
        conversationId: null,
      },
    );
    expect(clearPendingPrompt).toHaveBeenCalled();
  });

  it("does not send an unflagged prompt — that one fills the composer", () => {
    pendingPrompt = "summarise this page";
    pendingPromptAutoSend = false;

    render(<ChatPage />);

    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("sends once even if the effect re-runs", () => {
    pendingPrompt = "Hi! Who are you?";
    pendingPromptAutoSend = true;

    const { rerender } = render(<ChatPage />);
    rerender(<ChatPage />);

    expect(sendMessage).toHaveBeenCalledTimes(1);
  });
});
