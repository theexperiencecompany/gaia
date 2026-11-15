// @vitest-environment jsdom
/** While the voice chunk loads, the conversation stays on screen and the call can still be ended. */
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const { endVoiceCall } = vi.hoisted(() => ({ endVoiceCall: vi.fn() }));

// The app-router next/dynamic, which production resolves next/dynamic to.
vi.mock("next/dynamic", async () => ({
  default: (
    await vi.importActual<{ default: typeof import("next/dynamic").default }>(
      "next/dist/shared/lib/app-dynamic",
    )
  ).default,
}));

// LiveKit's chunk never arrives, so voice mode stays in its loading state.
vi.mock(
  "@/features/chat/components/voice-agent/VoiceControlBarContainer",
  () => new Promise<never>(() => undefined),
);

vi.mock(
  "@/features/chat/components/interface/hooks/useVoiceModeControls",
  () => ({
    useVoiceModeControls: () => ({
      voiceModeActive: true,
      onVoiceModeHover: vi.fn(),
      startVoiceMode: vi.fn(),
      endVoiceCall,
    }),
  }),
);

vi.mock(
  "@/features/chat/components/interface/layouts/ChatWithMessages",
  () => ({
    ChatWithMessages: ({ bottomBar }: { bottomBar: ReactNode }) => (
      <div>
        <p>conversation</p>
        {bottomBar}
      </div>
    ),
  }),
);

vi.mock("@/components/ui/message-scroller", () => ({
  MessageScrollerProvider: ({ children }: { children: ReactNode }) => children,
  useMessageScroller: () => ({ scrollToEnd: vi.fn() }),
}));
vi.mock("@/features/chat/components/interface/hooks/useChatLayout", () => ({
  useChatLayout: () => ({
    hasMessages: true,
    chatRef: { current: null },
    dummySectionRef: { current: null },
    inputRef: { current: null },
    fileUploadRef: { current: null },
    convoIdParam: "convo_1",
  }),
}));
vi.mock(
  "@/features/chat/components/interface/hooks/useWorkflowAutoSend",
  () => ({
    useWorkflowAutoSend: () => undefined,
  }),
);
vi.mock(
  "@/features/chat/components/interface/hooks/useActiveConversation",
  () => ({ useActiveConversation: () => undefined }),
);
vi.mock("@/features/chat/hooks/useStreamResume", () => ({
  useStreamResume: () => undefined,
}));
vi.mock("@/features/integrations/hooks/useIntegrations", () => ({
  useIntegrations: () => undefined,
}));
vi.mock("@/hooks/ui/useDragAndDrop", () => ({
  useDragAndDrop: () => ({ isDragging: false, dragHandlers: {} }),
}));
vi.mock("@/features/chat/components/composer/Composer", () => ({
  default: () => null,
}));
vi.mock("@/features/chat/components/composer/PaywallNotice", () => ({
  PaywallNotice: () => null,
}));
vi.mock("@/features/chat/components/files/FileDropModal", () => ({
  FileDropModal: () => null,
}));
vi.mock(
  "@/features/chat/components/interface/founder-letter/FounderLetter",
  () => ({ FounderLetter: () => null }),
);
vi.mock("@/features/chat/components/interface/layouts/NewChatLayout", () => ({
  NewChatLayout: () => null,
}));
vi.mock("@/features/chat/components/voice-agent/VoiceModeBackground", () => ({
  VoiceModeBackground: () => null,
}));
vi.mock("@/lib/toast", () => ({ toast: { error: vi.fn() } }));

import ChatPage from "@/features/chat/components/interface/ChatPage";

describe("ChatPage while the voice chunk loads", () => {
  it("shows the conversation with an end-call control", async () => {
    render(<ChatPage />);

    expect(await screen.findByText("conversation")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "End voice session" }));
    expect(endVoiceCall).toHaveBeenCalledTimes(1);
  });
});
