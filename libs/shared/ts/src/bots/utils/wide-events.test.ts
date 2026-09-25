import { afterEach, describe, expect, it, vi } from "vitest";
import { wideLog, withWideEvent } from "./wide-events";

/**
 * The Python twin of these assertions lives in
 * apps/api/tests/integration/api/test_wide_event_contracts.py. They are here
 * separately because the wide-event-conformance lane compares only the
 * TOP-LEVEL key -> JSON-type shape of an event: a namespace stays `"object"`
 * whether or not its keys survived, so that lane structurally cannot catch a
 * clobbering regression. These tests can.
 */

/** Run `body` inside a boundary and return the emitted event line, parsed. */
async function captureEvent(
  body: () => Promise<void>,
): Promise<Record<string, unknown>> {
  const lines: string[] = [];
  const spies = (["log", "warn", "error", "debug"] as const).map((level) =>
    vi.spyOn(console, level).mockImplementation((line: unknown) => {
      if (typeof line === "string") lines.push(line);
    }),
  );
  try {
    await withWideEvent(
      "test_task",
      { platform: "cli", component: "test" },
      body,
    );
  } finally {
    for (const spy of spies) spy.mockRestore();
  }

  const events = lines
    .map((line) => {
      try {
        return JSON.parse(line) as Record<string, unknown>;
      } catch {
        return undefined;
      }
    })
    .filter((e): e is Record<string, unknown> => e?.task === "test_task");

  expect(events).toHaveLength(1);
  return events[0];
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("wideLog.set namespace merging", () => {
  it("merges a second write of a namespace instead of replacing it", async () => {
    const event = await captureEvent(async () => {
      wideLog.set({ workflow: { id: "wf_1", trigger_type: "schedule" } });
      wideLog.set({ workflow: { status: "success", duration_ms: 12 } });
    });

    expect(event.workflow).toEqual({
      id: "wf_1",
      trigger_type: "schedule",
      status: "success",
      duration_ms: 12,
    });
  });

  it("treats set and setNs as interchangeable", async () => {
    const event = await captureEvent(async () => {
      wideLog.set({ todo: { operation: "create" } });
      wideLog.setNs("todo", { id: "t_1" });
      wideLog.set({ todo: { result_count: 2 } });
    });

    expect(event.todo).toEqual({
      operation: "create",
      id: "t_1",
      result_count: 2,
    });
  });

  it("does not merge a Date into the namespace it replaces", async () => {
    // `typeof new Date()` is "object", so a naive guard would spread it as a namespace, leaking
    // the PREVIOUS value's keys through (a Date has no own enumerable properties to overwrite
    // them with) — and admitting one here would split from Python's isinstance(x, dict) reject.

    // The Date still serializes to `{}` rather than an ISO string — a separate, pre-existing
    // serializer bug in logger.ts's toJsonValue (rebuilds objects from Object.entries()). What
    // this test pins is only that the stale `a` key does not survive.
    const event = await captureEvent(async () => {
      wideLog.set({ ctx: { a: 1 } });
      wideLog.set({
        ctx: new Date("2021-01-01T00:00:00Z") as unknown as number,
      });
    });

    expect(event.ctx).toEqual({});
  });

  it("replaces a class instance rather than merging into it", async () => {
    // The preceding namespace carries a key `stale` the instance does NOT, so merging is
    // observable: `stale` would survive a spread but must not survive a replace. (Two instances
    // of the same class would spread to the same result as replacing, proving nothing.)
    class Ctx {
      constructor(readonly label: string) {}
    }
    const event = await captureEvent(async () => {
      wideLog.set({ ctx: { stale: 1, label: "first" } });
      wideLog.set({
        ctx: new Ctx("second") as unknown as Record<string, unknown>,
      });
    });

    expect(event.ctx).toEqual({ label: "second" });
  });

  it("still replaces when either side is not a plain object", async () => {
    const event = await captureEvent(async () => {
      wideLog.set({ stage: "pending", todo: { operation: "create" } });
      wideLog.set({ stage: "done", todo: "replaced-by-scalar" });
    });

    expect(event.stage).toBe("done");
    expect(event.todo).toBe("replaced-by-scalar");
  });
});

describe("a failure the handler caught", () => {
  it("stays failed with its reason instead of being stamped success", async () => {
    const event = await captureEvent(async () => {
      wideLog.fail("account_not_linked", { http_status: 401 });
    });

    expect(event.outcome).toBe("failed");
    expect(event.reason).toBe("account_not_linked");
    expect(event.http_status).toBe(401);
  });
});
