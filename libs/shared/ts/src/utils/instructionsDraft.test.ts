import { describe, expect, it } from "vitest";

import { editInstructions, viewInstructionsDraft } from "./instructionsDraft";

const loadedAt = (revision: number, content = `v${revision}`) => ({
  content,
  revision,
});

describe("instructions draft", () => {
  it("saves against the revision the edit started from, not a later refetch", () => {
    const edit = editInstructions(null, "my edit", loadedAt(1));
    const view = viewInstructionsDraft(
      edit,
      loadedAt(2, "written by GAIA meanwhile"),
    );
    expect(view.base?.revision).toBe(1);
    expect(view.value).toBe("my edit");
  });

  it("keeps the first base across keystrokes", () => {
    const first = editInstructions(null, "a", loadedAt(1));
    const second = editInstructions(first, "ab", loadedAt(3));
    expect(second.base?.revision).toBe(1);
  });

  it("shows the loaded record when nothing is being edited", () => {
    const view = viewInstructionsDraft(null, loadedAt(4, "saved"));
    expect(view).toEqual({
      base: loadedAt(4, "saved"),
      value: "saved",
      isDirty: false,
    });
  });

  it("is dirty only when the draft differs from its base", () => {
    expect(
      viewInstructionsDraft(
        editInstructions(null, "v1", loadedAt(1)),
        loadedAt(1),
      ).isDirty,
    ).toBe(false);
    expect(
      viewInstructionsDraft(
        editInstructions(null, "v1!", loadedAt(1)),
        loadedAt(1),
      ).isDirty,
    ).toBe(true);
  });

  it("is never dirty before anything has loaded", () => {
    expect(viewInstructionsDraft(null, undefined)).toEqual({
      base: undefined,
      value: "",
      isDirty: false,
    });
  });
});
