/**
 * Tests for shared bot command handlers.
 *
 * These handlers are the core business logic used by all three bot platforms
 * (Discord, Slack, Telegram). A bug here affects every bot simultaneously.
 *
 * Tests verify:
 * - Correct GaiaClient method called with correct args
 * - Response formatted correctly on success
 * - formatBotError returned on API failure (never throws)
 * - Missing required args return usage hints instead of empty calls
 * - Subcommand dispatch routes to the right handler
 */

import type {
  TaskListResponse,
  TaskResponse,
} from "@gaia/shared/api/generated";
import type { CommandContext, GaiaClient } from "@gaia/shared/bots";
import {
  dispatchTaskSubcommand,
  dispatchWorkflowSubcommand,
  GaiaApiError,
  handleConversationList,
  handleNewConversation,
  handleTaskComplete,
  handleTaskCreate,
  handleTaskDelete,
  handleTaskList,
  handleWorkflowCreate,
  handleWorkflowDelete,
  handleWorkflowExecute,
  handleWorkflowGet,
  handleWorkflowList,
  helpCommand,
  type RichMessage,
  type RichMessageTarget,
  withWideEvent,
} from "@gaia/shared/bots";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { captureBotEvents } from "../helpers/capture-bot-event";
import { makeTask } from "../helpers/task-factory";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ctx: CommandContext = {
  platform: "telegram",
  platformUserId: "user-42",
  channelId: "chan-1",
  profile: null,
};

function taskList(tasks: TaskResponse[]): TaskListResponse {
  return { tasks, total: tasks.length, page: 1, per_page: 50 };
}

function makeGaia() {
  return {
    listWorkflows: vi.fn(),
    executeWorkflow: vi.fn(),
    getWorkflow: vi.fn(),
    createWorkflow: vi.fn(),
    deleteWorkflow: vi.fn(),
    listTasks: vi.fn(),
    createTask: vi.fn(),
    completeTask: vi.fn(),
    deleteTask: vi.fn(),
    listConversations: vi.fn(),
    resetSession: vi.fn(),
    getFrontendUrl: vi.fn().mockReturnValue("https://heygaia.io"),
  } as unknown as GaiaClient;
}

// ---------------------------------------------------------------------------
// Workflow handlers
// ---------------------------------------------------------------------------

describe("handleWorkflowList", () => {
  it("returns formatted workflow list on success", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.listWorkflows).mockResolvedValue({
      workflows: [
        {
          id: "wf-1",
          name: "Daily Standup",
          status: "active",
          description: "Posts standup",
        },
      ],
    } as never);

    const result = await handleWorkflowList(gaia, ctx);

    expect(gaia.listWorkflows).toHaveBeenCalledWith(ctx);
    expect(result).toContain("Daily Standup");
    expect(result).toContain("wf-1");
  });

  it("returns empty list message when no workflows", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.listWorkflows).mockResolvedValue({
      workflows: [],
    } as never);

    const result = await handleWorkflowList(gaia, ctx);

    expect(result).toContain("No workflows found");
  });

  it("returns error message on API failure", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.listWorkflows).mockRejectedValue(new Error("Network error"));

    const result = await handleWorkflowList(gaia, ctx);

    expect(result).toBe("❌ Something went wrong. Please try again later.");
  });
});

describe("handleWorkflowExecute", () => {
  it("returns execution started message with ID and status", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.executeWorkflow).mockResolvedValue({
      execution_id: "exec-123",
      status: "running",
    } as never);

    const result = await handleWorkflowExecute(gaia, "wf-1", ctx);

    expect(gaia.executeWorkflow).toHaveBeenCalledWith(
      { workflow_id: "wf-1", inputs: undefined },
      ctx,
    );
    expect(result).toContain("exec-123");
    expect(result).toContain("running");
  });

  it("passes inputs when provided", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.executeWorkflow).mockResolvedValue({
      execution_id: "exec-456",
      status: "running",
    } as never);

    await handleWorkflowExecute(gaia, "wf-2", ctx, { key: "value" });

    expect(gaia.executeWorkflow).toHaveBeenCalledWith(
      { workflow_id: "wf-2", inputs: { key: "value" } },
      ctx,
    );
  });

  it("returns error on failure", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.executeWorkflow).mockRejectedValue({
      response: { status: 404 },
    });

    const result = await handleWorkflowExecute(gaia, "missing", ctx);

    expect(result).toContain("Not found");
  });
});

describe("handleWorkflowGet", () => {
  it("returns formatted workflow on success", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.getWorkflow).mockResolvedValue({
      id: "wf-1",
      name: "My Workflow",
      status: "draft",
      description: "A test",
    } as never);

    const result = await handleWorkflowGet(gaia, "wf-1", ctx);

    expect(gaia.getWorkflow).toHaveBeenCalledWith("wf-1", ctx);
    expect(result).toContain("My Workflow");
  });

  it("returns not found on 404", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.getWorkflow).mockRejectedValue({
      response: { status: 404 },
    });

    const result = await handleWorkflowGet(gaia, "bad-id", ctx);

    expect(result).toContain("Not found");
  });
});

describe("handleWorkflowCreate", () => {
  it("returns created workflow with check emoji", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.createWorkflow).mockResolvedValue({
      id: "new-wf",
      name: "New Flow",
      status: "draft",
    } as never);

    const result = await handleWorkflowCreate(gaia, "New Flow", ctx, "Desc");

    expect(gaia.createWorkflow).toHaveBeenCalledWith(
      { name: "New Flow", description: "Desc" },
      ctx,
    );
    expect(result).toContain("✅");
    expect(result).toContain("New Flow");
  });

  it("uses empty string when no description provided", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.createWorkflow).mockResolvedValue({
      id: "wf-x",
      name: "Flow",
      status: "active",
    } as never);

    await handleWorkflowCreate(gaia, "Flow", ctx);

    expect(gaia.createWorkflow).toHaveBeenCalledWith(
      { name: "Flow", description: "" },
      ctx,
    );
  });
});

describe("handleWorkflowDelete", () => {
  it("returns success message on delete", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.deleteWorkflow).mockResolvedValue(undefined as never);

    const result = await handleWorkflowDelete(gaia, "wf-1", ctx);

    expect(gaia.deleteWorkflow).toHaveBeenCalledWith("wf-1", ctx);
    expect(result).toContain("✅");
    expect(result).toContain("deleted");
  });
});

// ---------------------------------------------------------------------------
// Task list handlers
// ---------------------------------------------------------------------------

describe("handleTaskList", () => {
  it("returns formatted task list on success", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.listTasks).mockResolvedValue(
      taskList([
        makeTask({ id: "t-1", title: "Buy milk" }),
        makeTask({ id: "t-2", title: "Read book", completed: true }),
      ]),
    );

    const result = await handleTaskList(gaia, ctx);

    expect(gaia.listTasks).toHaveBeenCalledWith(ctx, { completed: undefined });
    expect(result).toContain("Buy milk");
    expect(result).toContain("Read book");
  });

  it("passes completed filter when provided", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.listTasks).mockResolvedValue(taskList([]));

    await handleTaskList(gaia, ctx, true);

    expect(gaia.listTasks).toHaveBeenCalledWith(ctx, { completed: true });
  });

  it("returns error on API failure", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.listTasks).mockRejectedValue(new Error("timeout"));

    const result = await handleTaskList(gaia, ctx);

    expect(result).toContain("timed out");
  });
});

describe("handleTaskCreate", () => {
  it("returns created task with check emoji", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.createTask).mockResolvedValue(
      makeTask({ id: "t-new", title: "Finish tests" }),
    );

    const result = await handleTaskCreate(gaia, "Finish tests", ctx);

    expect(gaia.createTask).toHaveBeenCalledWith(
      { title: "Finish tests" },
      ctx,
    );
    expect(result).toContain("✅ Todo created!");
    expect(result).toContain("Finish tests");
  });

  it("passes priority and body when provided", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.createTask).mockResolvedValue(
      makeTask({ id: "t-x", title: "Urgent task", priority: "high" }),
    );

    await handleTaskCreate(gaia, "Urgent task", ctx, {
      priority: "high",
      body: "Very important",
    });

    expect(gaia.createTask).toHaveBeenCalledWith(
      { title: "Urgent task", priority: "high", body: "Very important" },
      ctx,
    );
  });

  it("returns auth error on 401", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.createTask).mockRejectedValue({ response: { status: 401 } });

    const result = await handleTaskCreate(gaia, "Task", ctx);

    expect(result).toContain("Authentication required");
    expect(result).toContain("/auth");
  });
});

describe("handleTaskComplete", () => {
  it("returns completion message with task title", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.completeTask).mockResolvedValue(
      makeTask({ title: "Buy groceries", completed: true }),
    );

    const result = await handleTaskComplete(gaia, "t-1", ctx);

    expect(gaia.completeTask).toHaveBeenCalledWith("t-1", ctx);
    expect(result).toBe("✅ Todo marked as complete: Buy groceries");
  });
});

describe("handleTaskDelete", () => {
  it("returns success message on delete", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.deleteTask).mockResolvedValue(undefined);

    const result = await handleTaskDelete(gaia, "t-1", ctx);

    expect(gaia.deleteTask).toHaveBeenCalledWith("t-1", ctx);
    expect(result).toBe("✅ Todo deleted successfully");
  });
});

// ---------------------------------------------------------------------------
// Conversation handlers
// ---------------------------------------------------------------------------

describe("handleConversationList", () => {
  it("returns formatted conversation list with frontend URLs", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.listConversations).mockResolvedValue({
      conversations: [
        {
          conversation_id: "c-1",
          title: "Work chat",
          message_count: 12,
        },
      ],
    } as never);
    vi.mocked(gaia.getFrontendUrl).mockReturnValue("https://heygaia.io");

    const result = await handleConversationList(gaia, ctx);

    expect(gaia.listConversations).toHaveBeenCalledWith(ctx, {
      page: 1,
      limit: 5,
    });
    expect(result).toContain("Work chat");
    expect(result).toContain("https://heygaia.io/c/c-1");
  });

  it("passes page parameter", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.listConversations).mockResolvedValue({
      conversations: [],
    } as never);

    await handleConversationList(gaia, ctx, 3);

    expect(gaia.listConversations).toHaveBeenCalledWith(ctx, {
      page: 3,
      limit: 5,
    });
  });
});

describe("helpCommand", () => {
  it("links to the instance the bot serves, not heygaia.io", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.getFrontendUrl).mockReturnValue("https://gaia.example.com");
    const sendRich = vi.fn().mockResolvedValue({});
    const target = { sendRich } as unknown as RichMessageTarget;

    await helpCommand.execute({ gaia, target, ctx, args: {} });

    const message = sendRich.mock.calls[0]?.[0] as RichMessage;
    expect(message.links?.map((link) => link.url)).toContain(
      "https://gaia.example.com",
    );
    expect(message.links?.map((link) => link.url)).not.toContain(
      "https://heygaia.io",
    );
  });
});

describe("handleNewConversation", () => {
  it("resets session and returns confirmation message", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.resetSession).mockResolvedValue(undefined as never);

    const result = await handleNewConversation(gaia, ctx);

    expect(gaia.resetSession).toHaveBeenCalledWith(
      "telegram",
      "user-42",
      "chan-1",
      undefined,
    );
    expect(result).toContain("new conversation");
    expect(result).toContain("previous conversation");
  });

  it("returns failure message on error (no error propagation)", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.resetSession).mockRejectedValue(
      new Error("Connection lost"),
    );

    const result = await handleNewConversation(gaia, ctx);

    expect(result).toContain("Something went wrong");
    expect(result).not.toContain("Connection lost");
  });

  it("an unlinked account's /new is a failed command naming why, and tells the user to link", async () => {
    const gaia = makeGaia();
    vi.mocked(gaia.resetSession).mockRejectedValue(
      new GaiaApiError("API error: 401", 401, {
        message: "This platform account is not linked to a GAIA account.",
        code: "BOT_ACCOUNT_NOT_LINKED",
      }),
    );

    let reply = "";
    const [event] = await captureBotEvents("command", () =>
      withWideEvent("command", { platform: "telegram" }, async () => {
        reply = await handleNewConversation(gaia, ctx);
      }),
    );

    expect(event).toMatchObject({
      outcome: "failed",
      reason: "account_not_linked",
      http_status: 401,
      error_code: "BOT_ACCOUNT_NOT_LINKED",
    });
    expect(event.errors).toEqual([
      expect.objectContaining({
        msg: "reset_session_failed",
        error_type: "GaiaApiError",
        http_status: 401,
        error_code: "BOT_ACCOUNT_NOT_LINKED",
      }),
    ]);
    expect(reply).toContain("Telegram account isn't linked to GAIA");
    expect(reply).toContain("/auth");
  });
});

// ---------------------------------------------------------------------------
// dispatchTaskSubcommand
// ---------------------------------------------------------------------------

describe("dispatchTaskSubcommand", () => {
  let gaia: ReturnType<typeof makeGaia>;

  beforeEach(() => {
    gaia = makeGaia();
    vi.mocked(gaia.listTasks).mockResolvedValue(taskList([]));
    vi.mocked(gaia.createTask).mockResolvedValue(
      makeTask({ id: "t-new", title: "New task" }),
    );
    vi.mocked(gaia.completeTask).mockResolvedValue(
      makeTask({ title: "Done task", completed: true }),
    );
    vi.mocked(gaia.deleteTask).mockResolvedValue(undefined);
  });

  it("routes 'list' to handleTaskList", async () => {
    await dispatchTaskSubcommand(gaia, ctx, "list", []);
    expect(gaia.listTasks).toHaveBeenCalled();
  });

  it("routes 'add' with title to handleTaskCreate", async () => {
    await dispatchTaskSubcommand(gaia, ctx, "add", ["Buy", "milk"]);
    expect(gaia.createTask).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Buy milk" }),
      ctx,
    );
  });

  it("returns usage hint when 'add' has no title", async () => {
    const result = await dispatchTaskSubcommand(gaia, ctx, "add", []);
    expect(result).toContain("Usage");
    expect(result).toContain("add");
    expect(gaia.createTask).not.toHaveBeenCalled();
  });

  it("routes 'complete' with ID to handleTaskComplete", async () => {
    await dispatchTaskSubcommand(gaia, ctx, "complete", ["t-1"]);
    expect(gaia.completeTask).toHaveBeenCalledWith("t-1", ctx);
  });

  it("returns usage hint when 'complete' has no ID", async () => {
    const result = await dispatchTaskSubcommand(gaia, ctx, "complete", []);
    expect(result).toContain("Usage");
    expect(gaia.completeTask).not.toHaveBeenCalled();
  });

  it("routes 'delete' with ID to handleTaskDelete", async () => {
    await dispatchTaskSubcommand(gaia, ctx, "delete", ["t-2"]);
    expect(gaia.deleteTask).toHaveBeenCalledWith("t-2", ctx);
  });

  it("returns usage hint when 'delete' has no ID", async () => {
    const result = await dispatchTaskSubcommand(gaia, ctx, "delete", []);
    expect(result).toContain("Usage");
    expect(gaia.deleteTask).not.toHaveBeenCalled();
  });

  it("returns full help for unknown subcommand", async () => {
    const result = await dispatchTaskSubcommand(gaia, ctx, "unknown", []);
    expect(result).toContain("/todo");
  });
});

// ---------------------------------------------------------------------------
// dispatchWorkflowSubcommand
// ---------------------------------------------------------------------------

describe("dispatchWorkflowSubcommand", () => {
  let gaia: ReturnType<typeof makeGaia>;

  beforeEach(() => {
    gaia = makeGaia();
    vi.mocked(gaia.listWorkflows).mockResolvedValue({ workflows: [] } as never);
    vi.mocked(gaia.getWorkflow).mockResolvedValue({
      id: "wf-1",
      name: "Flow",
      status: "active",
    } as never);
    vi.mocked(gaia.executeWorkflow).mockResolvedValue({
      execution_id: "exec-1",
      status: "running",
    } as never);
    vi.mocked(gaia.deleteWorkflow).mockResolvedValue(undefined as never);
  });

  it("routes 'list' to handleWorkflowList", async () => {
    await dispatchWorkflowSubcommand(gaia, ctx, "list", []);
    expect(gaia.listWorkflows).toHaveBeenCalled();
  });

  it("routes 'get' with ID to handleWorkflowGet", async () => {
    await dispatchWorkflowSubcommand(gaia, ctx, "get", ["wf-1"]);
    expect(gaia.getWorkflow).toHaveBeenCalledWith("wf-1", ctx);
  });

  it("returns usage hint when 'get' has no ID", async () => {
    const result = await dispatchWorkflowSubcommand(gaia, ctx, "get", []);
    expect(result).toContain("Usage");
    expect(gaia.getWorkflow).not.toHaveBeenCalled();
  });

  it("routes 'execute' with ID to handleWorkflowExecute", async () => {
    await dispatchWorkflowSubcommand(gaia, ctx, "execute", ["wf-1"]);
    expect(gaia.executeWorkflow).toHaveBeenCalledWith(
      expect.objectContaining({ workflow_id: "wf-1" }),
      ctx,
    );
  });

  it("returns usage hint when 'execute' has no ID", async () => {
    const result = await dispatchWorkflowSubcommand(gaia, ctx, "execute", []);
    expect(result).toContain("Usage");
    expect(gaia.executeWorkflow).not.toHaveBeenCalled();
  });

  it("routes 'delete' with ID to handleWorkflowDelete", async () => {
    await dispatchWorkflowSubcommand(gaia, ctx, "delete", ["wf-2"]);
    expect(gaia.deleteWorkflow).toHaveBeenCalledWith("wf-2", ctx);
  });

  it("returns usage hint when 'delete' has no ID", async () => {
    const result = await dispatchWorkflowSubcommand(gaia, ctx, "delete", []);
    expect(result).toContain("Usage");
    expect(gaia.deleteWorkflow).not.toHaveBeenCalled();
  });

  it("returns full workflow help for unknown subcommand", async () => {
    const result = await dispatchWorkflowSubcommand(gaia, ctx, "unknown", []);
    expect(result).toContain("/workflow");
  });
});
