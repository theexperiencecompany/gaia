import { describe, it, expect, vi, afterAll } from "vitest";
import {
  formatWorkflow,
  formatWorkflowList,
  formatTodo,
  formatTodoList,
  formatConversation,
  formatConversationList,
  convertToTelegramMarkdown,
  convertToSlackMrkdwn,
  formatAuthRequiredMessage,
  formatBotError,
  GaiaApiError,
} from "@gaia/shared";
import type { Workflow, Todo, Conversation } from "@gaia/shared";

// ---------------------------------------------------------------------------
// formatWorkflow
// ---------------------------------------------------------------------------
describe("formatWorkflow", () => {
  const base: Workflow = {
    id: "wf-1",
    name: "My Workflow",
    description: "Does things",
    status: "active",
  };

  it("shows check emoji for active workflow", () => {
    const result = formatWorkflow({ ...base, status: "active" });
    expect(result).toContain("\u2705");
  });

  it("shows pencil emoji for draft workflow", () => {
    const result = formatWorkflow({ ...base, status: "draft" });
    expect(result).toContain("\uD83D\uDCDD");
  });

  it("shows pause emoji for paused/inactive workflow", () => {
    const result = formatWorkflow({ ...base, status: "inactive" });
    expect(result).toContain("\u23F8");
  });

  it("includes name, ID, and description", () => {
    const result = formatWorkflow(base);
    expect(result).toContain("**My Workflow**");
    expect(result).toContain("`wf-1`");
    expect(result).toContain("Does things");
  });

  it('shows "No description" when description is empty', () => {
    const result = formatWorkflow({ ...base, description: "" });
    expect(result).toContain("No description");
  });
});

// ---------------------------------------------------------------------------
// formatWorkflowList
// ---------------------------------------------------------------------------
describe("formatWorkflowList", () => {
  it("returns create instruction for empty list", () => {
    const result = formatWorkflowList([]);
    expect(result).toContain("No workflows found");
    expect(result).toContain("/workflow create");
  });

  it("formats multiple workflows joined by double newlines", () => {
    const workflows: Workflow[] = [
      { id: "1", name: "A", description: "d1", status: "active" },
      { id: "2", name: "B", description: "d2", status: "draft" },
    ];
    const result = formatWorkflowList(workflows);
    expect(result).toContain("**A**");
    expect(result).toContain("**B**");
    expect(result.split("\n\n").length).toBeGreaterThanOrEqual(2);
  });
});

// ---------------------------------------------------------------------------
// formatTodo
// ---------------------------------------------------------------------------
describe("formatTodo", () => {
  const base: Todo = {
    id: "t-1",
    title: "Buy milk",
    completed: false,
  };

  it("shows checked checkbox for completed todo", () => {
    const result = formatTodo({ ...base, completed: true });
    expect(result).toContain("\u2611");
  });

  it("shows empty checkbox for incomplete todo", () => {
    const result = formatTodo({ ...base, completed: false });
    expect(result).toContain("\u2B1C");
  });

  it("uppercases priority", () => {
    const result = formatTodo({ ...base, priority: "high" });
    expect(result).toContain("[HIGH]");
  });

  it("formats due date correctly", () => {
    const result = formatTodo({ ...base, due_date: "2026-06-15T00:00:00Z" });
    expect(result).toContain("Due:");
    // The exact locale format varies, but it should contain the date
    expect(result).toMatch(/Due:\s*\d/);
  });

  it("omits priority when not set", () => {
    const result = formatTodo(base);
    expect(result).not.toContain("[");
  });

  it("omits due date when not set", () => {
    const result = formatTodo(base);
    expect(result).not.toContain("Due:");
  });
});

// ---------------------------------------------------------------------------
// formatTodoList
// ---------------------------------------------------------------------------
describe("formatTodoList", () => {
  it("returns create instruction for empty list", () => {
    const result = formatTodoList([]);
    expect(result).toContain("No todos found");
    expect(result).toContain("/todo add");
  });

  it("formats multiple todos joined by double newlines", () => {
    const todos: Todo[] = [
      { id: "1", title: "A", completed: false },
      { id: "2", title: "B", completed: true },
    ];
    const result = formatTodoList(todos);
    expect(result).toContain("**A**");
    expect(result).toContain("**B**");
  });
});

// ---------------------------------------------------------------------------
// formatConversation
// ---------------------------------------------------------------------------
describe("formatConversation", () => {
  const base: Conversation = {
    conversation_id: "c-1",
    created_at: "2026-01-01",
    updated_at: "2026-01-02",
    title: "Chat about cats",
    message_count: 5,
  };
  const baseUrl = "https://app.gaia.com";

  it("includes title, URL, and message count", () => {
    const result = formatConversation(base, baseUrl);
    expect(result).toContain("**Chat about cats**");
    expect(result).toContain("https://app.gaia.com/c/c-1");
    expect(result).toContain("(5 messages)");
  });

  it('shows "Untitled Conversation" when title is missing', () => {
    const result = formatConversation(
      { ...base, title: undefined },
      baseUrl,
    );
    expect(result).toContain("Untitled Conversation");
  });

  it("omits message count parenthetical when missing", () => {
    const result = formatConversation(
      { ...base, message_count: undefined },
      baseUrl,
    );
    expect(result).not.toContain("messages");
  });
});

// ---------------------------------------------------------------------------
// formatConversationList
// ---------------------------------------------------------------------------
describe("formatConversationList", () => {
  const baseUrl = "https://app.gaia.com";

  it("returns empty list message", () => {
    const result = formatConversationList([], baseUrl);
    expect(result).toContain("No conversations found");
  });

  it("joins multiple conversations with double newlines", () => {
    const conversations: Conversation[] = [
      {
        conversation_id: "1",
        title: "A",
        created_at: "2026-01-01",
        updated_at: "2026-01-01",
      },
      {
        conversation_id: "2",
        title: "B",
        created_at: "2026-01-01",
        updated_at: "2026-01-01",
      },
    ];
    const result = formatConversationList(conversations, baseUrl);
    expect(result).toContain("**A**");
    expect(result).toContain("**B**");
    expect(result).toContain("/c/1");
    expect(result).toContain("/c/2");
  });
});

// ---------------------------------------------------------------------------
// convertToTelegramMarkdown
// ---------------------------------------------------------------------------
describe("convertToTelegramMarkdown", () => {
  it("converts **bold** to *bold*", () => {
    expect(convertToTelegramMarkdown("Hello **world**")).toBe(
      "Hello *world*",
    );
  });

  it("converts ***bold italic*** to *bold*", () => {
    expect(convertToTelegramMarkdown("***text***")).toBe("*text*");
  });

  it("converts # Heading to *Heading*", () => {
    expect(convertToTelegramMarkdown("# My Heading")).toBe("*My Heading*");
  });

  it("strips > quote prefix", () => {
    expect(convertToTelegramMarkdown("> quoted text")).toBe("quoted text");
  });

  it("removes --- horizontal rule", () => {
    expect(convertToTelegramMarkdown("above\n---\nbelow")).toBe(
      "above\n\nbelow",
    );
  });

  it("preserves code blocks unchanged", () => {
    const input = "```\nconst x = 1;\n```";
    expect(convertToTelegramMarkdown(input)).toBe(input);
  });

  it("handles mixed content with code blocks and bold", () => {
    const input = "**bold** text\n```\ncode **here**\n```\n**more bold**";
    const result = convertToTelegramMarkdown(input);
    expect(result).toContain("*bold*");
    expect(result).toContain("```\ncode **here**\n```");
    expect(result).toContain("*more bold*");
  });
});

// ---------------------------------------------------------------------------
// convertToSlackMrkdwn
// ---------------------------------------------------------------------------
describe("convertToSlackMrkdwn", () => {
  it("converts **bold** to *bold*", () => {
    expect(convertToSlackMrkdwn("Hello **world**")).toBe("Hello *world*");
  });

  it("converts [label](url) to <url|label>", () => {
    expect(convertToSlackMrkdwn("[Click here](https://example.com)")).toBe(
      "<https://example.com|Click here>",
    );
  });

  it("converts # Heading to *Heading*", () => {
    expect(convertToSlackMrkdwn("## Sub Heading")).toBe("*Sub Heading*");
  });

  it("preserves code blocks unchanged", () => {
    const input = "```\nsome code\n```";
    expect(convertToSlackMrkdwn(input)).toBe(input);
  });
});

// ---------------------------------------------------------------------------
// formatAuthRequiredMessage
// ---------------------------------------------------------------------------
describe("formatAuthRequiredMessage", () => {
  it("capitalizes platform name", () => {
    const result = formatAuthRequiredMessage(
      "discord",
      "https://auth.gaia.com",
    );
    expect(result).toContain("Discord");
  });

  it("includes auth URL", () => {
    const url = "https://auth.gaia.com/link";
    const result = formatAuthRequiredMessage("slack", url);
    expect(result).toContain(url);
  });

  it("includes custom context", () => {
    const result = formatAuthRequiredMessage(
      "telegram",
      "https://auth.gaia.com",
      "manage your todos",
    );
    expect(result).toContain("manage your todos");
  });

  it("uses default context when none provided", () => {
    const result = formatAuthRequiredMessage(
      "discord",
      "https://auth.gaia.com",
    );
    expect(result).toContain("use this feature");
  });
});

// ---------------------------------------------------------------------------
// formatBotError
// ---------------------------------------------------------------------------
describe("formatBotError", () => {
  // Suppress console.error for the generic error fallback tests
  const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

  it("returns auth message for GaiaApiError with 401", () => {
    const err = new GaiaApiError("Unauthorized", 401);
    const result = formatBotError(err);
    expect(result).toContain("Authentication required");
    expect(result).toContain("/auth");
  });

  it("returns not found message for 404 status", () => {
    const err = { response: { status: 404 }, message: "Not found" };
    const result = formatBotError(err);
    expect(result).toContain("Not found");
  });

  it("returns rate limit message for 429 status", () => {
    const err = new GaiaApiError("Rate limited", 429);
    const result = formatBotError(err);
    expect(result).toContain("too fast");
  });

  it("returns timeout message for timeout errors", () => {
    const err = new Error("Request timed out");
    const result = formatBotError(err);
    expect(result).toContain("timed out");
  });

  it("returns connection message for connection lost", () => {
    const err = new Error("Connection lost before receiving a response");
    const result = formatBotError(err);
    expect(result).toContain("Connection lost");
  });

  it("returns connection interrupted for ECONNRESET", () => {
    const err = new Error("ECONNRESET");
    const result = formatBotError(err);
    expect(result).toContain("Connection interrupted");
  });

  it("returns incomplete message for stream processing", () => {
    const err = new Error("Stream processing incomplete");
    const result = formatBotError(err);
    expect(result).toContain("incomplete");
  });

  it('returns "something went wrong" for generic Error', () => {
    const err = new Error("some random failure");
    const result = formatBotError(err);
    expect(result).toContain("Something went wrong");
  });

  it('returns "something went wrong" for non-Error value', () => {
    const result = formatBotError("just a string");
    expect(result).toContain("Something went wrong");
  });

  afterAll(() => {
    consoleSpy.mockRestore();
  });
});
