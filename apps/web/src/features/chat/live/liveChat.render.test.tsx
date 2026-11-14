// @vitest-environment jsdom
import type { ConversationFrame } from "@shared/conversation";
import {
  founderConversationFrames,
  insertFrame,
  replyDelta,
  replyItem,
  userItem,
} from "@shared/conversation/testing";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen } from "@testing-library/react";
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
import { useChatStore } from "@/stores/chatStore";
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

const FOUNDER_ROWS = ["u1", "u2", "work:c4f22a9a", "u3", "r2.1"];

/** The founder conversation's row ids, in the order the DOM shows them. */
const shownRows = () =>
  FOUNDER_ROWS.map((id) => document.getElementById(id))
    .filter((node): node is HTMLElement => node !== null)
    .sort((a, b) =>
      a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1,
    )
    .map((node) => node.id);

describe("the chat rendered from the server's screen patches", () => {
  it("renders the founder's conversation without ever moving a shown row", async () => {
    renderChat();
    let shown: string[] = [];
    for (const frame of founderConversationFrames()) {
      await feed(frame);
      const now = shownRows();
      expect(now.filter((id) => shown.includes(id))).toEqual(shown);
      shown = now;
    }
    expect(shown).toEqual(FOUNDER_ROWS);
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
});
