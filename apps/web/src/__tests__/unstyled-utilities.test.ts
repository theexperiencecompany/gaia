import { describe, expect, it } from "vitest";
import {
  classesIn,
  tailwindUtilities,
  unstyledUtilities,
} from "../../e2e/worker/unstyled-utilities";

describe("classesIn", () => {
  it("unescapes the variant, fraction and arbitrary-value characters of a utility", () => {
    expect(classesIn(".md\\:hover\\:bg-zinc-800\\/40:hover")).toEqual([
      "md:hover:bg-zinc-800/40",
    ]);
    expect(classesIn(".w-\\[37px\\]")).toEqual(["w-[37px]"]);
  });

  it("decodes the hex escape a browser writes for a leading digit", () => {
    expect(classesIn(".\\32 xl\\:grid")).toEqual(["2xl:grid"]);
  });

  it("does not read a class out of a quoted attribute value", () => {
    expect(classesIn('[data-file=".flex"] .grid')).toEqual(["grid"]);
    expect(classesIn("a[href$='.pdf']")).toEqual([]);
  });

  it("returns every class of a compound or nested selector", () => {
    expect(
      classesIn(".group-hover\\:flex:is(:where(.group):hover *), a.btn > b"),
    ).toEqual(["group-hover:flex", "group", "btn"]);
  });
});

describe("tailwindUtilities", () => {
  it("keeps plain, variant, arbitrary-value and theme-token utilities", async () => {
    const candidates = [
      "inline-flex",
      "md:hover:bg-zinc-800/40",
      "w-[37px]",
      "2xl:grid",
      "before:border-[color:var(--border)]",
      "text-accent-foreground",
      "space-x-4",
    ];
    expect(await tailwindUtilities(candidates)).toEqual(new Set(candidates));
  });

  it("drops component classes, variant markers and unknown names", async () => {
    const utilities = await tailwindUtilities([
      "navbar",
      "chat_bubble",
      "button--primary",
      "group",
      "peer",
      "dark",
      "group-hover:flex",
      "dark:bg-red-500",
      "not-a-utility",
    ]);
    expect(utilities).toEqual(new Set(["group-hover:flex", "dark:bg-red-500"]));
  });
});

describe("unstyledUtilities", () => {
  it("reports the rendered utilities no selector mentions, and nothing else", async () => {
    const unstyled = await unstyledUtilities({
      classes: ["flex", "inline-flex", "md:px-4", "h-10", "navbar", "group"],
      selectors: [".flex", ".md\\:px-4", ".flex-col", ".other .h-1"],
    });
    expect(unstyled).toEqual(["h-10", "inline-flex"]);
  });

  it("is empty when every rendered utility has a rule", async () => {
    const unstyled = await unstyledUtilities({
      classes: ["inline-flex", "hover:opacity-80", "navbar"],
      selectors: [".inline-flex", ".hover\\:opacity-80:hover"],
    });
    expect(unstyled).toEqual([]);
  });
});
