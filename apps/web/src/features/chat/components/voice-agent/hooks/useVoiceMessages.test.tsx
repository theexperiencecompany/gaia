// @vitest-environment jsdom
import {
  entryFrame,
  reply,
  replySettled,
  userMessage,
} from "@shared/conversation/testing";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type StreamHandler = (reader: { readAll: () => Promise<string> }) => unknown;

const room = vi.hoisted(() => ({
  name: "voice-room",
  handlers: new Map<string, StreamHandler>(),
  localParticipant: { identity: "user-1", sendText: vi.fn() },
  registerTextStreamHandler(topic: string, handler: StreamHandler) {
    this.handlers.set(topic, handler);
  },
  unregisterTextStreamHandler(topic: string) {
    this.handlers.delete(topic);
  },
}));
const transcriptions = vi.hoisted(() => ({
  current: [] as Array<{
    text: string;
    streamInfo: { id: string };
    participantInfo: { identity: string };
  }>,
}));

vi.mock("@livekit/components-react", () => ({
  useRoomContext: () => room,
  useTranscriptions: () => transcriptions.current,
}));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "conv-1" }),
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
  usePathname: () => "/c/conv-1",
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/components/ui/message-scroller", () => ({
  MessageScrollerItem: ({ children }: { children: ReactNode }) => (
    <div data-testid="row">{children}</div>
  ),
}));
vi.mock("@/features/chat/components/image/GeneratedImageSheet", () => ({
  default: () => null,
}));
vi.mock("@/features/chat/components/memory/MemoryModal", () => ({
  default: () => null,
}));
vi.mock("@/features/chat/components/bubbles/bot/SearchedImageDialog", () => ({
  default: () => null,
}));

import ChatRenderer from "@/features/chat/components/interface/ChatRenderer";
import { VOICE_STREAM_TOPIC } from "@/features/chat/components/voice-agent/constants";
import { useLiveConversationStore } from "@/features/chat/live/liveConversationStore";
import { useChatStore } from "@/stores/chatStore";
import { useVoiceMessages } from "./useVoiceMessages";

const CONVERSATION = "conv-1";
const SPOKEN = "what is on today";
const ANSWER = "You have two meetings";

function VoiceChat() {
  useVoiceMessages(CONVERSATION);
  return <ChatRenderer />;
}

const dataChannel = (payload: Record<string, unknown>) =>
  act(async () => {
    await room.handlers.get(VOICE_STREAM_TOPIC)?.({
      readAll: async () => JSON.stringify(payload),
    });
  });

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(vi.fn());
  room.handlers.clear();
  transcriptions.current = [];
  useLiveConversationStore.setState({ conversations: {} });
  useChatStore.setState({
    activeConversationId: CONVERSATION,
    messagesByConversation: {},
    optimisticMessage: null,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the voice screen", () => {
  it("shows a spoken turn and its answer once each, from the conversation's events", async () => {
    const { rerender } = render(
      <QueryClientProvider client={new QueryClient()}>
        <VoiceChat />
      </QueryClientProvider>,
    );

    transcriptions.current = [
      {
        text: SPOKEN,
        streamInfo: { id: "tr-1" },
        participantInfo: { identity: "user-1" },
      },
    ];
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <VoiceChat />
      </QueryClientProvider>,
    );
    await dataChannel({ conversation_id: CONVERSATION });
    await dataChannel({ response: ANSWER, message_id: "a1" });
    act(() => {
      useLiveConversationStore
        .getState()
        .applyFrames(CONVERSATION, [
          entryFrame(1, userMessage("m1", SPOKEN)),
          entryFrame(2, reply("a1", "attempt-1", ANSWER)),
          entryFrame(3, replySettled("a1", ["m1"], 1)),
        ]);
    });

    const rows = screen.getAllByTestId("row").map((row) => row.textContent);
    expect(rows.filter((text) => text?.includes(SPOKEN))).toHaveLength(1);
    expect(rows.filter((text) => text?.includes(ANSWER))).toHaveLength(1);
  });
});
