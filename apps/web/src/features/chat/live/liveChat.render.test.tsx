// @vitest-environment jsdom
import {
  type ConversationFrame,
  DISPLAY_STATE,
  REPLY_OUTCOME,
  SEND_NOT_DELIVERED,
} from "@shared/conversation";
import {
  founderConversationFrames,
  insertFrame,
  replyDelta,
  replyItem,
  stateFrame,
  updateFrame,
  userItem,
} from "@shared/conversation/testing";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
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
vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ profilePicture: "" }),
}));

import ChatRenderer from "@/features/chat/components/interface/ChatRenderer";
import { useChatStore } from "@/stores/chatStore";
import { useLiveConversationStore } from "./liveConversationStore";

const CONVERSATION = "conv-1";

const feed = (...frames: ConversationFrame[]) =>
  act(() => {
    useLiveConversationStore.getState().applyFrames(CONVERSATION, frames);
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

/** The row a screen item renders as; every user message carries its own Retry, so a reply's is read here. */
function screenRow(id: string): HTMLElement {
  const row = document.querySelector<HTMLElement>(
    `[data-screen-item-id="${id}"]`,
  );
  if (!row) throw new Error(`no row rendered for screen item ${id}`);
  return row;
}

const failedReply = (id: string, seq: number, retryTarget: string | null) => ({
  ...replyItem(id, seq, "", "failed"),
  failure: "model_error" as const,
  failure_line: "Something went wrong on my side.",
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

  // Bug 16: a reload replays the streaming reply's deltas back to back, each SSE message its own
  // store write. Applied faster than React gets to the markdown's follow-up render, past 50 in a
  // row React threw "Maximum update depth exceeded" out of the write and the events stream dropped.
  it("applies a replayed burst of reply deltas without a nested-update loop", async () => {
    renderChat();
    await feed(
      insertFrame(userItem("m1", 1, "write an essay")),
      insertFrame(replyItem("r1", 2, "")),
      stateFrame(2, DISPLAY_STATE.THINKING),
    );
    const deltas = 120;
    for (let index = 0; index < deltas; index++) {
      useLiveConversationStore
        .getState()
        .applyFrames(CONVERSATION, [replyDelta("a1", "r1", index, " word")]);
      // Each SSE message is its own task: React's sync work flushes, its scheduled render waits.
      await Promise.resolve();
    }
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    const loops = vi
      .mocked(console.error)
      .mock.calls.filter((call) =>
        String(call[0]).includes("Maximum update depth"),
      );
    expect(loops).toEqual([]);
    expect(document.body.textContent).toContain(" word".repeat(deltas).trim());
  });

  // web-e2e-screen: a reply's later bubble showed in full while an earlier one still read "Part",
  // because each bubble deferred its own text and a bubble mounting in the same render did not.
  it("shows a streaming multi-bubble reply only as states the reply passed through", async () => {
    renderChat();
    await feed(
      insertFrame(userItem("m1", 1, "three parts")),
      insertFrame(replyItem("r1", 2, "")),
      stateFrame(2, DISPLAY_STATE.THINKING),
    );
    const deltas: [string, number][] = [
      ["Part", 0],
      [" one.", 0],
      ["Part", 1],
      [" two.", 1],
      ["Part", 2],
      [" three.", 2],
    ];
    const passed: string[][] = [[]];
    const shown: string[][] = [];
    const bubbles = () =>
      Array.from(
        screenRow("r1").querySelectorAll<HTMLElement>(".imessage-bubble"),
      ).map((bubble) => bubble.textContent?.trim() ?? "");
    for (const [index, [text, bubble]] of deltas.entries()) {
      const next = [...(passed.at(-1) ?? [])];
      next[bubble] = (next[bubble] ?? "") + text;
      passed.push(next);
      useLiveConversationStore
        .getState()
        .applyFrames(CONVERSATION, [
          replyDelta("a1", "r1", index, text, bubble),
        ]);
      // The store write renders in a microtask; a deferred render waits for a task.
      await Promise.resolve();
      shown.push(bubbles());
    }
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    shown.push(bubbles());
    const passedThrough = new Set(passed.map((state) => JSON.stringify(state)));
    expect(
      shown.filter((state) => !passedThrough.has(JSON.stringify(state))),
    ).toEqual([]);
    expect(shown.at(-1)).toEqual(["Part one.", "Part two.", "Part three."]);
  });

  // web-e2e-screen: the idle state hid the loading line at once while the row it ended, patched in
  // the same burst, still waited on the row's deferred render, so the screen showed neither.
  it("never hides the loading line before the row it stood in for shows", async () => {
    renderChat();
    await feed(
      insertFrame(userItem("m1", 1, "two parts")),
      insertFrame(replyItem("r1", 2, "Part one.")),
      stateFrame(2, DISPLAY_STATE.THINKING),
    );
    const lastPartShown = () =>
      screenRow("r1").textContent?.includes("Part two.") ?? false;
    const loadingShown = () =>
      document.querySelector('[data-testid="chat-loading-row"]') !== null;
    useLiveConversationStore
      .getState()
      .applyFrames(CONVERSATION, [
        updateFrame(
          replyItem(
            "r1",
            2,
            ["Part one.", "Part two."],
            REPLY_OUTCOME.ANSWERED,
          ),
        ),
        stateFrame(2, DISPLAY_STATE.IDLE),
      ]);
    // The store write renders in a microtask; a deferred render waits for a task.
    await Promise.resolve();
    expect(loadingShown() || lastPartShown()).toBe(true);
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    expect([loadingShown(), lastPartShown()]).toEqual([false, true]);
  });

  it("words a failed reply with nothing shown in the server's failure line", async () => {
    renderChat();
    const failed = {
      ...replyItem("r1", 2, "", "failed"),
      failure: "step_limit" as const,
      failure_line: "The server's own words for a step-limit stop.",
    };
    await feed(
      insertFrame(userItem("m1", 1, "do it all")),
      insertFrame(failed),
    );
    expect(
      screen.getByText("The server's own words for a step-limit stop."),
    ).toBeDefined();
  });

  it("offers no retry on a failed reply the server names nothing to retry for", async () => {
    renderChat();
    await feed(
      insertFrame(userItem("m1", 1, "hi")),
      insertFrame(failedReply("r1", 2, null)),
    );
    expect(
      within(screenRow("r1")).queryByRole("button", { name: "Retry" }),
    ).toBeNull();
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
