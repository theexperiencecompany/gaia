import { describe, expect, it } from "vitest";

import { tabsVariants } from "./tabsVariants";

// The skills page's "Your Skills" tab and the New skill modal's "Import from
// GitHub" tab wrapped onto two lines inside their fit-width lists; v2's never did.
describe("tabsVariants", () => {
  it("keeps every tab label on one line", () => {
    expect(tabsVariants({ variant: "solid" }).tab().split(/\s+/)).toContain(
      "whitespace-nowrap",
    );
  });
});
