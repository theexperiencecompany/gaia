// @vitest-environment jsdom

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";

const PRICES = "Aug 2026 $347.53 USD standout; Sep 2026 $8 succeeded.";

describe("MarkdownRenderer dollar signs", () => {
  it("renders a single dollar sign as currency, not math", () => {
    const { container } = render(<MarkdownRenderer content={PRICES} />);
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toContain(PRICES);
  });

  it("renders inline double-dollar math", () => {
    const { container } = render(
      <MarkdownRenderer content="Energy is $$E=mc^2$$ here." />,
    );
    expect(container.querySelector(".katex")).not.toBeNull();
  });

  it("renders a double-dollar block as display math", () => {
    const { container } = render(
      <MarkdownRenderer content={"$$\n\\int_0^1 x\\,dx\n$$"} />,
    );
    expect(container.querySelector(".katex-display")).not.toBeNull();
  });
});
