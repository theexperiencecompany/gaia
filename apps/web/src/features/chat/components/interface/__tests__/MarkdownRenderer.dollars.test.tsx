// @vitest-environment jsdom
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";

vi.mock("@/stores/uiStore", () => ({
  useImageDialog: () => ({ open: vi.fn() }),
}));

// The pasted canvas.md line that rendered as a formula, one letter per line.
const PRICES = "Aug 2026 $347.53 USD standout; Sep 2026 $8 succeeded.";

describe("MarkdownRenderer dollar amounts", () => {
  it("keeps prices as text when inline dollar math is off", async () => {
    const { container } = render(
      <MarkdownRenderer content={PRICES} inlineDollarMath={false} />,
    );

    await waitFor(() =>
      expect(container.textContent).toContain("$347.53 USD standout"),
    );
    expect(container.querySelector(".katex")).toBeNull();
  });

  it("renders text between two dollar signs as math by default", async () => {
    const { container } = render(<MarkdownRenderer content={PRICES} />);

    await waitFor(() =>
      expect(container.querySelector(".katex")).not.toBeNull(),
    );
  });
});
