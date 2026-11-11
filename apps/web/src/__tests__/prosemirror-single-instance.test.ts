// The instructions editor (Tiptap) breaks on the first keystroke with "Can not
// convert <...> to a Fragment" when two copies of prosemirror-model load: the
// view builds nodes from one copy and the state checks them against the other.

import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const requireFromWeb = createRequire(import.meta.url);

/** The prosemirror-model file a module at fromFile gets when it imports it. */
const modelSeenFrom = (fromFile: string): string =>
  createRequire(fromFile).resolve("prosemirror-model");

describe("prosemirror-model", () => {
  it("is one copy for Tiptap and for the prosemirror-view it renders with", () => {
    const tiptapModel = requireFromWeb.resolve("@tiptap/pm/model");
    const tiptapView = requireFromWeb.resolve("@tiptap/pm/view");
    const prosemirrorView =
      createRequire(tiptapView).resolve("prosemirror-view");
    const prosemirrorState = createRequire(
      requireFromWeb.resolve("@tiptap/pm/state"),
    ).resolve("prosemirror-state");

    const seen = new Set([
      modelSeenFrom(tiptapModel),
      modelSeenFrom(prosemirrorView),
      modelSeenFrom(prosemirrorState),
    ]);

    expect([...seen]).toHaveLength(1);
  });
});
