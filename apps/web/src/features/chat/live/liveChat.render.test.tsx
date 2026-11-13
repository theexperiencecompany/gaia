// @vitest-environment jsdom
import type { ConversationFrame, LoggedEntry } from "@shared/conversation";
import {
  entryFrame,
  entryUpdatedFrame,
  liveTask,
  notice,
  reply,
  replyDelta,
  replySettled,
  stateFrame,
  todoWoke,
  toolCallCard,
  userMessage,
  workCardDelta,
  workFinished,
  workflowFired,
  workStarted,
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

const loadingRowShown = () => screen.queryByTestId("chat-loading-row") !== null;

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

describe("the chat rendered from the conversation's events", () => {
  it("shows a message sent during a streaming reply under it, with the loading row still up", async () => {
    renderChat();
    await feed(
      entryFrame(1, userMessage("m1", "what is on today")),
      stateFrame(1, "thinking"),
      replyDelta("a1", null, 0, "You have two meetings"),
    );
    await send("m2", "and tomorrow?");

    const rows = screen.getAllByTestId("row").map((row) => row.textContent);
    expect(rows[0]).toContain("what is on today");
    expect(rows[1]).toContain("You have two meetings");
    expect(rows[2]).toContain("and tomorrow?");
    expect(loadingRowShown()).toBe(true);
  });

  it("keeps the loading row while work runs, also after a second message lands", async () => {
    renderChat();
    await feed(
      entryFrame(1, userMessage("m1", "book a table")),
      entryFrame(2, workStarted("t1", 1)),
      stateFrame(2, "working", [liveTask("t1")]),
    );
    expect(loadingRowShown()).toBe(true);
    expect(screen.getByText("Working on it")).toBeDefined();

    await send("m2", "for four people");
    await feed(
      entryFrame(3, userMessage("m2", "for four people")),
      stateFrame(3, "thinking", [liveTask("t1")]),
      entryFrame(4, reply("r2", "a2", "Noted, four people.")),
      entryFrame(5, replySettled("r2", ["m2"], 3)),
      stateFrame(5, "working", [liveTask("t1")]),
    );

    expect(screen.getByText("Noted, four people.")).toBeDefined();
    expect(loadingRowShown()).toBe(true);
  });

  it("shows a reaction-only answer as the reaction on the message, with no empty bubble", async () => {
    renderChat();
    await feed(
      entryFrame(1, userMessage("m1", "thanks!")),
      stateFrame(1, "thinking"),
      entryUpdatedFrame(
        1,
        userMessage("m1", "thanks!", { emoji: "🙌", by: "chat_model" }, 1),
      ),
      entryFrame(2, replySettled("r1", ["m1"], 1, null, "silent")),
      stateFrame(2, "idle"),
    );

    expect(screen.getByText("🙌")).toBeDefined();
    expect(screen.getAllByTestId("row")).toHaveLength(1);
    expect(loadingRowShown()).toBe(false);
  });

  it("rebuilds a reply that was streaming at reload from the saved log and the replay", async () => {
    const saved: LoggedEntry[] = [
      {
        seq: 1,
        at: "2026-11-12T10:00:00+00:00",
        entry: userMessage("m1", "draft my email"),
      },
      {
        seq: 2,
        at: "2026-11-12T10:00:00+00:00",
        entry: reply("r1", "a1"),
      },
    ];
    act(() => {
      useLiveConversationStore.getState().restore(CONVERSATION, {
        entries: saved,
        olderBefore: null,
        sends: {},
      });
    });
    renderChat();
    expect(screen.getByText("draft my email")).toBeDefined();

    await feed(
      entryFrame(1, userMessage("m1", "draft my email")),
      entryFrame(2, reply("r1", "a1")),
      stateFrame(2, "thinking"),
      replyDelta("a1", "r1", 0, "Dear team, "),
      replyDelta("a1", "r1", 1, "here is the update."),
    );

    expect(screen.getByText("Dear team, here is the update.")).toBeDefined();
    expect(screen.getAllByTestId("row")).toHaveLength(2);
  });

  it("shows the loading row from the send until the reply settles, with no gap", async () => {
    renderChat();
    await send("m1", "what is on today");
    expect(loadingRowShown()).toBe(true);

    // Accepted: the entry lands before the state frame that says thinking.
    await feed(entryFrame(1, userMessage("m1", "what is on today")));
    expect(loadingRowShown()).toBe(true);

    await feed(stateFrame(1, "thinking"));
    expect(loadingRowShown()).toBe(true);

    await feed(replyDelta("a1", null, 0, "You have two meetings"));
    expect(loadingRowShown()).toBe(true);

    await feed(
      entryFrame(2, reply("r1", "a1", "You have two meetings")),
      entryFrame(3, replySettled("r1", ["m1"], 1)),
      stateFrame(3, "idle"),
    );
    expect(screen.getByText("You have two meetings")).toBeDefined();
    expect(loadingRowShown()).toBe(false);
  });

  it("shows no loading row after a reload for a message of this device's already answered", async () => {
    const saved: LoggedEntry[] = [
      { seq: 1, at: "2026-11-12T10:00:00+00:00", entry: userMessage("m1") },
      {
        seq: 2,
        at: "2026-11-12T10:00:00+00:00",
        entry: reply("r1", "a1", "done"),
      },
      {
        seq: 3,
        at: "2026-11-12T10:00:00+00:00",
        entry: replySettled("r1", ["m1"], 1),
      },
    ];
    act(() => {
      useLiveConversationStore.getState().restore(CONVERSATION, {
        entries: saved,
        olderBefore: null,
        sends: {
          m1: {
            body: { message_id: "m1", text: "hi" },
            fileData: [],
            failed: false,
          },
        },
      });
    });
    renderChat();
    expect(loadingRowShown()).toBe(false);
  });

  it("shows an attachment from the logged message on a device that did not send it", async () => {
    renderChat();
    await feed(
      entryFrame(1, {
        ...userMessage("m1", "summarise this"),
        file_ids: ["f1"],
        files: [
          {
            fileId: "f1",
            filename: "q3-report.pdf",
            url: "https://f/q3.pdf",
            type: "application/pdf",
          },
        ],
      }),
    );
    expect(screen.getByText(/q3-report/)).toBeDefined();
  });

  it("marks a failed reply that streamed text as cut short", async () => {
    renderChat();
    await feed(
      entryFrame(1, userMessage("m1", "draft it")),
      entryFrame(2, reply("r1", "a1", "Here is the start")),
      entryFrame(3, replySettled("r1", [], 1, null, "failed", "model_error")),
      stateFrame(3, "idle"),
    );
    expect(screen.getByText("Here is the start")).toBeDefined();
    expect(screen.getByText("Response was cut short")).toBeDefined();
  });

  it("words a failed reply with nothing shown by why it failed", async () => {
    renderChat();
    await feed(
      entryFrame(1, userMessage("m1", "do it all")),
      entryFrame(2, reply("r1", "a1")),
      entryFrame(3, replySettled("r1", [], 1, null, "failed", "step_limit")),
      stateFrame(3, "idle"),
    );
    expect(
      screen.getByText(
        "GAIA took too many steps on this and stopped before answering.",
      ),
    ).toBeDefined();
  });

  it("keeps a stopped task's cards on screen, marked stopped", async () => {
    renderChat();
    await feed(
      entryFrame(1, userMessage("m1", "email the landlord")),
      entryFrame(2, workStarted("t1", 1)),
      stateFrame(2, "working", [liveTask("t1")]),
      workCardDelta("t1", 0, "Drafting the email"),
    );
    expect(screen.getAllByTestId("row")).toHaveLength(2);

    await feed(
      entryFrame(3, workFinished("t1", "cancelled")),
      stateFrame(3, "idle"),
    );

    expect(screen.getAllByTestId("row")).toHaveLength(2);
    expect(screen.getByText("Stopped")).toBeDefined();
    expect(loadingRowShown()).toBe(false);
  });

  it("shows a workflow run as its workflow card, then its reply", async () => {
    renderChat();
    await feed(
      entryFrame(1, workflowFired("f1", "Morning brief")),
      entryFrame(2, reply("r1", "a1", "Three meetings today.")),
      entryFrame(3, replySettled("r1", ["f1"], 1)),
    );

    const rows = screen.getAllByTestId("row").map((row) => row.textContent);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toContain("Morning brief");
    expect(rows[1]).toContain("Three meetings today.");
  });

  it("shows a todo run as what woke it, then its write-up", async () => {
    renderChat();
    await feed(
      entryFrame(1, todoWoke("w1")),
      entryFrame(2, workStarted("t1", 1)),
      entryFrame(3, workFinished("t1")),
      entryFrame(4, reply("t1", "a1", "The invoice was paid.")),
      entryFrame(5, replySettled("t1", ["w1"], 3)),
    );

    const rows = screen.getAllByTestId("row").map((row) => row.textContent);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toContain("Scheduled run");
    expect(rows[1]).toContain("The invoice was paid.");
  });

  it("shows a notice as GAIA's message with the cards it was delivered with", async () => {
    renderChat();
    await feed(
      entryFrame(
        1,
        notice("n1", "Your reminder: call the bank", [
          toolCallCard("c1", "Checked the calendar"),
        ]),
      ),
    );

    const [row] = screen.getAllByTestId("row");
    expect(row.textContent).toContain("Your reminder: call the bank");
    expect(row.textContent).toContain("Used 1 tool");
  });
});
