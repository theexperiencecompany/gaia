// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, waitFor } from "@testing-library/react";
import postcss, { type Rule } from "postcss";
import { describe, expect, it } from "vitest";

import { FileViewerBody } from "@/features/chat/components/artifacts/FileViewerBody";

const GLOBALS_CSS = join(__dirname, "../app/styles/globals.css");
// The highlighter loads its grammar lazily; a cold run takes well over waitFor's 1s default.
const HIGHLIGHT_TIMEOUT_MS = 10_000;

/** Global rules that pad a `code` element: on a block's inline <code> that shifts line 1 alone. */
function codePaddingSelectors(): string[] {
  const selectors: string[] = [];
  postcss.parse(readFileSync(GLOBALS_CSS, "utf8")).walkRules((rule: Rule) => {
    const pads = rule.nodes.some(
      (node) => node.type === "decl" && node.prop.startsWith("padding"),
    );
    if (pads)
      selectors.push(...rule.selectors.filter((s) => /\bcode\b/.test(s)));
  });
  return selectors;
}

describe("the file viewer's source view", () => {
  it("pads no line of the highlighted code, so line 1 lines up with the rest", async () => {
    const { container } = render(
      <FileViewerBody
        isImage={false}
        isPdf={false}
        loading={false}
        error={false}
        content={"month,revenue\nJan,120\nFeb,140"}
        contentType="text/csv"
        filename="revenue.csv"
        fileUrl=""
        viewMode="source"
      />,
    );
    const code = await waitFor(
      () => {
        const element = container.querySelector("pre > code");
        if (!element?.querySelector(".linenumber"))
          throw new Error("not highlighted yet");
        return element;
      },
      { timeout: HIGHLIGHT_TIMEOUT_MS },
    );

    const selectors = codePaddingSelectors();
    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) {
      expect(code.matches(selector), selector).toBe(false);
    }
  });
});
