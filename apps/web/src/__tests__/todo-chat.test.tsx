// @vitest-environment jsdom
import {
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  useConversationList,
  useConversationRow,
} from "@/features/chat/hooks/useConversationList";
import { todoApi } from "@/features/todo/api/todoApi";
import { OpenTodoChatButton } from "@/features/todo/components/OpenTodoChatButton";
import { TodoChatBackLink } from "@/features/todo/components/TodoChatBackLink";
import type { IConversation } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

const push = vi.fn();
let routeParams: { id?: string } = {};

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useParams: () => routeParams,
}));

vi.mock("@/features/todo/api/todoApi", () => ({
  todoApi: { openTodoConversation: vi.fn() },
}));

function conversation(
  id: string,
  overrides: Partial<IConversation> = {},
): IConversation {
  return {
    id,
    title: `Chat ${id}`,
    description: `Chat ${id}`,
    createdAt: new Date("2026-10-01T00:00:00Z"),
    updatedAt: new Date("2026-10-01T00:00:00Z"),
    ...overrides,
  };
}

beforeEach(() => {
  useChatStore.setState({
    conversations: [
      conversation("chat-1"),
      conversation("todo-chat", {
        todoId: "todo-1",
        description: "Watch the deploy",
      }),
    ],
  });
});

afterEach(() => {
  vi.clearAllMocks();
  routeParams = {};
  useChatStore.setState({ conversations: [] });
});

describe("a tracked todo's chat in the conversation lists", () => {
  it("is never in the list the user browses", () => {
    const { result } = renderHook(() => useConversationList());

    expect(result.current.conversations.map((c) => c.conversation_id)).toEqual([
      "chat-1",
    ]);
  });

  it("is still found by id, so its own page has its title and flags", () => {
    const { result } = renderHook(() => useConversationRow("todo-chat"));

    expect(result.current?.description).toBe("Watch the deploy");
    expect(result.current?.todo_id).toBe("todo-1");
  });
});

describe("Open chat", () => {
  it("opens the chat the server names for the todo", async () => {
    vi.mocked(todoApi.openTodoConversation).mockResolvedValue({
      conversation_id: "todo-chat",
    });

    render(<OpenTodoChatButton todoId="todo-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Open chat" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/c/todo-chat"));
    expect(todoApi.openTodoConversation).toHaveBeenCalledWith("todo-1");
  });
});

describe("Back to task", () => {
  it("leads from a todo's chat back to its todo", () => {
    routeParams = { id: "todo-chat" };

    render(<TodoChatBackLink />);

    expect(
      screen.getByRole("button", { name: "Back to task" }).getAttribute("href"),
    ).toBe("/todos?todoId=todo-1");
  });

  it("is absent from any other chat", () => {
    routeParams = { id: "chat-1" };

    render(<TodoChatBackLink />);

    expect(screen.queryByText("Back to task")).toBeNull();
  });
});
