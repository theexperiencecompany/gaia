// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import type React from "react";
import { describe, expect, it, vi } from "vitest";

import { RunsOnlyWhenField } from "@/features/workflows/triggers/components/RunsOnlyWhenField";

const BILLING = "the email is from a customer about billing";
const INVOICES = "the email is about an invoice";
const DESK_TEXT = "a real person or a real obligation is waiting on you";

describe("the runs-only-when row", () => {
  const renderRow = (
    overrides: Partial<React.ComponentProps<typeof RunsOnlyWhenField>> = {},
  ) => {
    const props = {
      condition: BILLING,
      enabled: true,
      editable: true,
      enforced: true,
      onConditionChange: vi.fn(),
      onEnabledChange: vi.fn(),
      ...overrides,
    };
    render(<RunsOnlyWhenField {...props} />);
    return props;
  };

  it("hands each edit of the condition to its owner", () => {
    const { onConditionChange } = renderRow();

    fireEvent.change(screen.getByRole("textbox", { name: "Runs only when" }), {
      target: { value: INVOICES },
    });

    expect(onConditionChange).toHaveBeenCalledWith(INVOICES);
  });

  it("turns the gate off from its switch", () => {
    const { onEnabledChange } = renderRow();

    fireEvent.click(screen.getByRole("switch"));

    expect(onEnabledChange).toHaveBeenCalledWith(false);
  });

  it("shows a system gate's wording without letting it be rewritten", () => {
    renderRow({ condition: DESK_TEXT, editable: false });

    expect(screen.getByText(DESK_TEXT)).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("switch")).toBeTruthy();
  });

  it("says a rule still being checked skips no runs yet", () => {
    renderRow({ enforced: false });

    expect(
      screen.getByText(
        "GAIA is still learning this rule. Every event runs for now.",
      ),
    ).toBeTruthy();
  });

  it("says nothing about checking once the rule can skip runs", () => {
    renderRow({ enforced: true });

    expect(screen.queryByText(/still learning/)).toBeNull();
  });
});
