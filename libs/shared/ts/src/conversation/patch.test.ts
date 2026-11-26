import { describe, expect, it } from "vitest";
import type { ItemChange } from "../api/generated";
import refusals from "./fixtures/patch-refusals.json";
import { applyChanges } from "./patch";

const held = {
  status: "running",
  timeline: {
    steps: [
      { key: "tc-a", data: { id: "a", output: "first" } },
      { key: "tc-b", data: { id: "b", reasoning: "think" } },
    ],
    progress: null as { message: string } | null,
  },
};

const set = (path: ItemChange["path"], value: ItemChange["value"]) =>
  ({ op: "set", path, value }) satisfies ItemChange;
const append = (path: ItemChange["path"], value: string) =>
  ({ op: "append", path, value }) satisfies ItemChange;
const remove = (path: ItemChange["path"]) =>
  ({ op: "remove", path, value: null }) satisfies ItemChange;

describe("applying the changes a wire 2 stream sends", () => {
  it("lands an output on one call and shares every step it did not touch", () => {
    const next = applyChanges(held, [
      set(["timeline", "steps", 1, "data", "output"], "second"),
    ]);

    expect(next?.timeline.steps[1].data).toEqual({
      id: "b",
      reasoning: "think",
      output: "second",
    });
    expect(next?.timeline.steps[0]).toBe(held.timeline.steps[0]);
    expect(held.timeline.steps[1].data).not.toHaveProperty("output");
  });

  it("appends a new step at the index past the end, and text to a string", () => {
    const step = { key: "tc-c", data: { id: "c" } };
    const next = applyChanges(held, [
      set(["timeline", "steps", 2], step),
      append(["timeline", "steps", 1, "data", "reasoning"], "ing"),
      set(["status"], "done"),
    ]);

    expect(next?.timeline.steps).toHaveLength(3);
    expect(next?.timeline.steps[2]).toEqual(step);
    expect(next?.timeline.steps[1].data).toMatchObject({
      reasoning: "thinking",
    });
    expect(next?.status).toBe("done");
  });

  it("drops a key, and a list's last element", () => {
    const next = applyChanges(held, [
      remove(["timeline", "steps", 0, "data", "output"]),
      remove(["timeline", "steps", 1]),
    ]);

    expect(next?.timeline.steps).toEqual([{ key: "tc-a", data: { id: "a" } }]);
  });

  it("sets a key the held value lacks", () => {
    expect(applyChanges(held, [set(["added_later"], { inner: 1 })])).toEqual({
      ...held,
      added_later: { inner: 1 },
    });
  });

  // The Python applier refuses the same cases (apps/api/tests/unit/services/conversation/test_item_changes.py).
  it.each(refusals.refused.map(({ name, change }) => [name, change]))(
    "refuses %s: the copy is not the one it was written against",
    (_name, change) => {
      expect(applyChanges(refusals.held, [change as ItemChange])).toBeNull();
    },
  );
});
