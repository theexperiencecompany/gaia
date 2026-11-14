// @vitest-environment jsdom
import {
  type ConversationFrame,
  SEND_NOT_DELIVERED,
} from "@shared/conversation";
import {
  founderConversationFrames,
  insertFrame,
  replyDelta,
  replyItem,
  stateFrame,
  userItem,
} from "@shared/conversation/testing";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  MessageScrollerItem: ({
    children,
    messageId: _messageId,
    scrollAnchor: _scrollAnchor,
    ...rest
  }: {
    children: ReactNode;
    messageId: string;
    scrollAnchor: boolean;
  }) => <div {...rest}>{children}</div>,
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
vi.mock("./connection", async (actual) => ({
  ...(await actual<Record<string, unknown>>()),
  deliverRetry: vi.fn(),
}));

import ChatRenderer from "@/features/chat/components/interface/ChatRenderer";
import { useChatStore } from "@/stores/chatStore";
import { deliverRetry } from "./connection";
import { useLiveConversationStore } from "./liveConversationStore";

const CONVERSATION = "conv-1";

const feed = (...frames: ConversationFrame[]) =>
  act(() => {
    useLiveConversationStore.getState().applyFrames(CONVERSATION, frames);
  });

const send = (id: string, text: string) =>
  act(() => {
    useLiveConversationStore.getState().queueSend(CONVERSATION, {
      body: { message_id: id, text },
      fileData: [],
      failed: false,
    });
  });

const renderChat = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ChatRenderer />
    </QueryClientProvider>,
  );

/** Every rendered row's screen item id and kind, in DOM order. */
const shownRows = () =>
  Array.from(
    document.querySelectorAll<HTMLElement>("[data-screen-item-id]"),
  ).map((node) => [node.dataset.screenItemId, node.dataset.screenItemKind]);

const failedReply = (id: string, seq: number, retryTarget: string | null) => ({
  ...replyItem(id, seq, "", "failed"),
  failure: "model_error" as const,
  retry_target: retryTarget,
});

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(vi.fn());
  useLiveConversationStore.setState({ conversations: {} });
  useChatStore.setState({
    activeConversationId: CONVERSATION,
    optimisticMessage: null,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const FOUNDER_ROWS = [
  ["u1", "user"],
  ["u2", "user"],
  ["work:c4f22a9a", "work"],
  ["u3", "user"],
  ["r2.1", "reply"],
];

describe("the chat rendered from the server's screen patches", () => {
  it("renders the founder's conversation without ever moving a shown row", async () => {
    renderChat();
    let shown: string[] = [];
    for (const frame of founderConversationFrames()) {
      await feed(frame);
      const now = shownRows().map(([id]) => id as string);
      expect(now.filter((id) => shown.includes(id))).toEqual(shown);
      shown = now;
    }
    expect(shownRows()).toEqual(FOUNDER_ROWS);
  });

  it("shows this device's send under the streaming reply, then in the server's place", async () => {
    renderChat();
    await feed(insertFrame(userItem("m1", 1, "first")));
    await feed(insertFrame(replyItem("r1", 2, "Hel")));
    await feed(replyDelta("a1", "r1", 0, "Hello there"));
    send("m2", "second");
    expect(screen.getByText("Hello there")).toBeDefined();
    expect(screen.getByText("second")).toBeDefined();
    await feed(insertFrame(userItem("m2", 3, "second")));
    expect(screen.getAllByText("second")).toHaveLength(1);
  });

  it("words a failed reply with nothing shown by why it failed", async () => {
    renderChat();
    const failed = {
      ...replyItem("r1", 2, "", "failed"),
      failure: "step_limit" as const,
    };
    await feed(
      insertFrame(userItem("m1", 1, "do it all")),
      insertFrame(failed),
    );
    expect(
      screen.getByText(
        "GAIA took too many steps on this and stopped before answering.",
      ),
    ).toBeDefined();
  });

  it("retries a failed reply by asking the server to answer the message it names", async () => {
    renderChat();
    await feed(
      insertFrame(userItem("m1", 1, "book the flight")),
      insertFrame(userItem("m2", 2, "and a hotel")),
      insertFrame(failedReply("r1", 3, "m1")),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(vi.mocked(deliverRetry)).toHaveBeenCalledExactlyOnceWith(
      CONVERSATION,
      "m1",
    );
  });

  it("offers no retry on a failed reply the server names nothing to retry for", async () => {
    renderChat();
    await feed(
      insertFrame(userItem("m1", 1, "hi")),
      insertFrame(failedReply("r1", 2, null)),
    );
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("shows the progress line the server states for the streaming reply", async () => {
    renderChat();
    await feed(
      insertFrame(userItem("m1", 1, "email bob")),
      stateFrame(1, "working"),
      {
        kind: "reply_delta",
        attempt_id: "a1",
        reply_id: null,
        index: 0,
        payload: {
          type: "cards",
          tool_data: [],
          timeline: {
            steps: [],
            cards: [],
            progress: {
              message: "Sending the email",
              tool_name: "gmail_send",
              tool_category: "gmail",
              integration_name: null,
              icon_url: null,
              show_category: true,
            },
          },
        },
      },
    );
    expect(screen.getByTestId("chat-loading-row").textContent).toBe(
      "Gmail: Sending the email",
    );
  });

  it("shows a new conversation's failed first send as not delivered", () => {
    useChatStore.setState({
      activeConversationId: null,
      optimisticMessage: {
        id: "optimistic-1",
        conversationId: null,
        content: "the message the user typed",
        role: "user",
        createdAt: new Date("2026-01-01T00:00:00Z"),
        failed: true,
      },
    });
    renderChat();
    expect(screen.getByText("the message the user typed")).toBeDefined();
    expect(screen.getByText(SEND_NOT_DELIVERED)).toBeDefined();
    expect(shownRows()).toEqual([["optimistic-1", "user"]]);
  });
});
