import { describe, expect, it } from "vitest";
import type { ItemChange } from "../api/generated";
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

  it("leaves the held value alone when a change is under a key this build does not keep", () => {
    const next = applyChanges(held, [
      set(["added_later", "inner"], 1),
      append(["added_later"], "text"),
      set(["status"], "done"),
    ]);

    expect(next).toEqual({ ...held, status: "done" });
  });

  it.each([
    ["an index past the end", set(["timeline", "steps", 5, "data"], 1)],
    ["a set two past the end", set(["timeline", "steps", 3], 1)],
    ["an append to a list", append(["timeline", "steps"], "x")],
    [
      "a removal that is not the last element",
      remove(["timeline", "steps", 0]),
    ],
    ["a key into a list", set(["timeline", "steps", "key", "x"], 1)],
    ["an index into a record", set(["timeline", 0, "x"], 1)],
  ])(
    "refuses %s: the copy is not the one it was written against",
    (_name, change) => {
      expect(applyChanges(held, [change])).toBeNull();
    },
  );
});
