/** The signed-in app tells crawlers not to index it, on top of robots.txt keeping them out. */
import { describe, expect, it } from "vitest";

import { metadata } from "@/app/[locale]/(main)/layout";

describe("(main) app layout", () => {
  it("marks every app page noindex", () => {
    expect(metadata.robots).toEqual({ index: false, follow: false });
  });
});
