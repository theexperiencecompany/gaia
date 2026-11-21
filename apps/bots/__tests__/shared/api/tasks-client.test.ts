/**
 * The /todo command's API calls through the real GaiaClient, with only the
 * axios transport faked: which /api/v1/tasks route each call hits, with what.
 */
import type { TaskListResponse } from "@gaia/shared/api/generated";
import { type CommandContext, GaiaClient } from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";
import { makeTask } from "../helpers/task-factory";

const ctx: CommandContext = {
  platform: "telegram",
  platformUserId: "user-42",
  channelId: "chan-1",
  profile: undefined,
};

function gaiaWithTransport() {
  const task = makeTask();
  const list: TaskListResponse = {
    tasks: [task],
    total: 1,
    page: 1,
    per_page: 50,
  };
  const transport = {
    get: vi.fn(async () => ({ data: list })),
    post: vi.fn(async () => ({ data: task })),
    put: vi.fn(async () => ({ data: { ...task, completed: true } })),
    delete: vi.fn(async () => ({ data: undefined })),
  };
  const gaia = new GaiaClient("http://gaia.test", "bot-key", "http://web.test");
  (gaia as unknown as { client: unknown }).client = transport;
  return { gaia, transport, list };
}

describe("GaiaClient task calls", () => {
  it("lists top-level tasks and returns the API's body as is", async () => {
    const { gaia, transport, list } = gaiaWithTransport();

    const result = await gaia.listTasks(ctx);

    expect(transport.get).toHaveBeenCalledWith(
      "/api/v1/tasks?top_level=true",
      expect.anything(),
    );
    expect(result).toEqual(list);
  });

  it("passes the completed filter on the list query", async () => {
    const { gaia, transport } = gaiaWithTransport();

    await gaia.listTasks(ctx, { completed: false });

    expect(transport.get).toHaveBeenCalledWith(
      "/api/v1/tasks?top_level=true&completed=false",
      expect.anything(),
    );
  });

  it("creates a task with title, priority and body", async () => {
    const { gaia, transport } = gaiaWithTransport();

    await gaia.createTask(
      { title: "Buy milk", priority: "high", body: "2 litres" },
      ctx,
    );

    expect(transport.post).toHaveBeenCalledWith(
      "/api/v1/tasks",
      { title: "Buy milk", priority: "high", body: "2 litres" },
      expect.anything(),
    );
  });

  it("completes a task with a PUT of completed: true", async () => {
    const { gaia, transport } = gaiaWithTransport();

    const result = await gaia.completeTask("t/1", ctx);

    expect(transport.put).toHaveBeenCalledWith(
      "/api/v1/tasks/t%2F1",
      { completed: true },
      expect.anything(),
    );
    expect(result.completed).toBe(true);
  });

  it("deletes a task by id", async () => {
    const { gaia, transport } = gaiaWithTransport();

    await gaia.deleteTask("t-1", ctx);

    expect(transport.delete).toHaveBeenCalledWith(
      "/api/v1/tasks/t-1",
      expect.anything(),
    );
  });
});
