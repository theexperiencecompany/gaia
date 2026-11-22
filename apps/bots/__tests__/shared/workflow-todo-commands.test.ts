/**
 * `/workflow` and `/todo` through the real GaiaClient and formatters, with only
 * the axios transport faked. Server payloads are typed by the generated API
 * models, so a reply that reads a field the API never sends fails here.
 */
import type {
  CreateWorkflowRequest,
  TaskListResponse,
  WorkflowExecutionResponse,
  WorkflowListResponse,
  WorkflowResponse,
} from "@gaia/shared/api/generated";
import {
  type CommandContext,
  GaiaClient,
  type RichMessageTarget,
  todoCommand,
  workflowCommand,
} from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";
import { serverTask, serverWorkflow } from "./helpers/api-fixtures";

const ctx: CommandContext = { platform: "discord", platformUserId: "u-1" };

interface Transport {
  get: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
  put: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
}

function gaiaWith(responses: {
  get?: unknown;
  post?: unknown;
  put?: unknown;
}): { gaia: GaiaClient; transport: Transport } {
  const transport: Transport = {
    get: vi.fn(async () => ({ data: responses.get })),
    post: vi.fn(async () => ({ data: responses.post })),
    put: vi.fn(async () => ({ data: responses.put })),
    delete: vi.fn(async () => ({ data: undefined })),
  };
  const gaia = new GaiaClient("http://gaia.test", "bot-key", "http://web.test");
  (gaia as unknown as { client: Transport }).client = transport;
  return { gaia, transport };
}

function replyTarget(): RichMessageTarget & { sent: string[] } {
  const sent: string[] = [];
  const record = async (text: string) => {
    sent.push(text);
    return { id: "m", edit: async () => undefined };
  };
  return {
    sent,
    platform: "discord",
    send: vi.fn(record),
    sendEphemeral: vi.fn(record),
    sendRich: vi.fn(async () => ({ id: "m", edit: async () => undefined })),
    startTyping: vi.fn(async () => () => undefined),
  } as unknown as RichMessageTarget & { sent: string[] };
}

async function run(
  command: typeof workflowCommand,
  gaia: GaiaClient,
  args: Record<string, string | boolean | undefined>,
  rawText?: string,
): Promise<string> {
  const target = replyTarget();
  await command.execute({ gaia, target, ctx, args, rawText });
  return target.sent.join("\n");
}

describe("/workflow", () => {
  it("lists each workflow by its title and whether it is on", async () => {
    const list: WorkflowListResponse = {
      workflows: [
        serverWorkflow({ id: "wf-on", title: "Morning brief" }),
        serverWorkflow({
          id: "wf-off",
          title: "Weekly digest",
          activated: false,
        }),
      ],
    };
    const { gaia } = gaiaWith({ get: list });

    const reply = await run(workflowCommand, gaia, { subcommand: "list" });

    expect(reply).toContain("✅ **Morning brief**");
    expect(reply).toContain("⏸️ **Weekly digest**");
    expect(reply).not.toContain("undefined");
  });

  it("creates a manual workflow the API accepts from a title and instructions", async () => {
    const created: WorkflowResponse = {
      message: "Workflow created",
      workflow: serverWorkflow({ title: "Standup" }),
    };
    const { gaia, transport } = gaiaWith({ post: created });

    const reply = await run(workflowCommand, gaia, {
      subcommand: "create",
      title: "Standup",
      instructions: "Summarise what I did yesterday",
    });

    const expected: CreateWorkflowRequest = {
      title: "Standup",
      prompt: "Summarise what I did yesterday",
      trigger_config: { type: "manual", enabled: true },
    };
    expect(transport.post).toHaveBeenCalledWith(
      "/api/v1/workflows",
      expected,
      expect.anything(),
    );
    expect(reply).toMatch(/^✅ Workflow created!/);
    expect(reply).toContain("**Standup**");
  });

  it("creates from text input: first word is the title, the rest the instructions", async () => {
    const created: WorkflowResponse = {
      message: "Workflow created",
      workflow: serverWorkflow({ title: "Standup" }),
    };
    const { gaia, transport } = gaiaWith({ post: created });

    await run(
      workflowCommand,
      gaia,
      { subcommand: "create" },
      "create Standup Summarise what I did yesterday",
    );

    expect(transport.post.mock.calls[0]?.[1]).toMatchObject({
      title: "Standup",
      prompt: "Summarise what I did yesterday",
    });
  });

  it("asks for instructions instead of sending a request the API rejects", async () => {
    const { gaia, transport } = gaiaWith({});

    const reply = await run(
      workflowCommand,
      gaia,
      { subcommand: "create" },
      "create Standup",
    );

    expect(transport.post).not.toHaveBeenCalled();
    expect(reply).toContain("/workflow create <title> <instructions>");
  });

  it("reports a started run by its execution id, not a missing status", async () => {
    const started: WorkflowExecutionResponse = {
      execution_id: "exec-9",
      message: "Workflow execution started",
    };
    const { gaia } = gaiaWith({ post: started });

    const reply = await run(workflowCommand, gaia, {
      subcommand: "execute",
      id: "wf-1",
    });

    expect(reply).toContain("✅ Workflow execution started");
    expect(reply).toContain("exec-9");
    expect(reply).not.toContain("undefined");
    expect(reply).not.toContain("BotWorkflow");
  });
});

describe("/todo", () => {
  it("lists todos without a priority tag for priority none", async () => {
    const list: TaskListResponse = {
      tasks: [
        serverTask({ id: "t-plain", title: "Buy milk", priority: "none" }),
        serverTask({ id: "t-urgent", title: "File taxes", priority: "high" }),
      ],
      total: 2,
      page: 1,
      per_page: 50,
    };
    const { gaia } = gaiaWith({ get: list });

    const reply = await run(todoCommand, gaia, { subcommand: "list" });

    expect(reply).toContain("**Buy milk**");
    expect(reply).toContain("**File taxes** [HIGH]");
    expect(reply).not.toContain("[NONE]");
  });

  it("confirms a created todo without rename debris", async () => {
    const { gaia } = gaiaWith({ post: serverTask({ title: "Call mum" }) });

    const reply = await run(todoCommand, gaia, {
      subcommand: "add",
      title: "Call mum",
    });

    expect(reply).toMatch(/^✅ Todo created!/);
    expect(reply).toContain("**Call mum**");
    expect(reply).not.toContain("[NONE]");
  });
});
