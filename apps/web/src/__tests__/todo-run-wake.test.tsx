// @vitest-environment jsdom
import type { TodoRunWake } from "@shared/api/generated";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TodoRunWakeIndicator } from "@/features/chat/components/bubbles/user/TodoRunWakeIndicator";
import { mapStoredMessageToConversationMessage } from "@/features/chat/hooks/useConversation";
import { triggerEventLabel } from "@/features/todo/utils/todoRunWake";
import type { IMessage } from "@/lib/db/chatDb";

const WAKE: TodoRunWake = {
  todo_id: "todo-1",
  todo_title: "Watch the staging deploy",
  kind: "schedule",
  trigger_names: [],
  approval_summary: null,
};

afterEach(() => {
  vi.clearAllMocks();
});

describe("what woke a tracked todo's run", () => {
  it("words the events that woke it, not trigger ids", () => {
    expect(triggerEventLabel("gmail_new_message")).toBe("on new emails");
  });

  it("falls back to the trigger id it has no words for", () => {
    expect(triggerEventLabel("acme_widget_moved")).toBe("on acme_widget_moved");
  });

  it("carries a stored wake to the user bubble", () => {
    const stored: IMessage = {
      id: "m-1",
      conversationId: "todo-chat",
      content: "",
      role: "user",
      status: "sent",
      createdAt: new Date("2026-10-31T14:05:00Z"),
      updatedAt: new Date("2026-10-31T14:05:00Z"),
      todoRunWake: WAKE,
    };

    expect(mapStoredMessageToConversationMessage(stored).todo_run_wake).toEqual(
      WAKE,
    );
  });

  it("renders as the user's side of the run, with its label", () => {
    render(<TodoRunWakeIndicator wake={WAKE} />);

    expect(screen.getByText("Scheduled run")).toBeTruthy();
  });

  it("renders the registry's words for a triggered run", () => {
    render(
      <TodoRunWakeIndicator
        wake={{
          ...WAKE,
          kind: "trigger",
          trigger_names: ["gmail_email_sent", "gmail_new_message"],
        }}
      />,
    );

    expect(
      screen.getByText("Woke up on sent emails and on new emails"),
    ).toBeTruthy();
  });
});
