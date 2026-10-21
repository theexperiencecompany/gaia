// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ErrorBoundary from "./ErrorBoundary";

function Card({ items }: Readonly<{ items: unknown }>) {
  return <span>{(items as string[]).join(", ")}</span>;
}

describe("ErrorBoundary with an item fallback", () => {
  it("shows the fallback, then recovers when the reset key brings good data", () => {
    vi.spyOn(console, "error").mockImplementation(vi.fn());
    const onError = vi.fn();

    const view = (items: unknown) => (
      <ErrorBoundary
        fallback={<span>card failed</span>}
        resetKey={items}
        onError={onError}
      >
        <Card items={items} />
      </ErrorBoundary>
    );
    const { rerender } = render(view("not-a-list"));

    expect(screen.getByText("card failed")).toBeDefined();
    expect(onError).toHaveBeenCalledOnce();

    rerender(view(["milk", "eggs"]));

    expect(screen.getByText("milk, eggs")).toBeDefined();
    expect(screen.queryByText("card failed")).toBeNull();
  });
});
