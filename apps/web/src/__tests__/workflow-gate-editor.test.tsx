// @vitest-environment jsdom

import type { AuthoredGateView, SystemGateView } from "@shared/api/generated";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type React from "react";
import { describe, expect, it, vi } from "vitest";

import { RunsOnlyWhenPanel } from "@/features/workflows/triggers/components/RunsOnlyWhenPanel";

const BILLING = "the email is from a customer about billing";
const INVOICES = "the email is about an invoice";
const DESK_TEXT = "a real person or a real obligation is waiting on you";
const OLDER = {
  event: 'Substack, "Weekly digest"',
  at: "2026-11-05T08:00:00Z",
};
const NEWER = { event: 'Uber, "Your receipt"', at: "2026-11-05T09:00:00Z" };

const saved = (
  overrides: Partial<AuthoredGateView> = {},
): AuthoredGateView => ({
  kind: "authored",
  condition: BILLING,
  display_condition: BILLING,
  author: "gaia",
  enabled: true,
  enforced: true,
  recent_skips: [],
  ...overrides,
});

const DESK: SystemGateView = {
  kind: "system",
  preset: "inbox_desk",
  display_condition: DESK_TEXT,
  enabled: true,
  enforced: true,
  recent_skips: [],
};

describe("the runs-only-when panel", () => {
  const renderPanel = (
    overrides: Partial<React.ComponentProps<typeof RunsOnlyWhenPanel>> = {},
    { expanded = true } = {},
  ) => {
    const props = {
      condition: BILLING,
      enabled: true,
      saved: saved() as AuthoredGateView | SystemGateView | null,
      editable: true,
      onConditionSave: vi.fn(),
      onEnabledChange: vi.fn(),
      ...overrides,
    };
    render(<RunsOnlyWhenPanel {...props} />);
    if (expanded) {
      fireEvent.click(screen.getByRole("button", { expanded: false }));
    }
    return props;
  };

  it("stays one row until expanded: the rule and its switch, nothing else", () => {
    renderPanel(
      { saved: saved({ recent_skips: [NEWER] }) },
      { expanded: false },
    );

    expect(screen.getByText(BILLING)).toBeTruthy();
    expect(screen.getByRole("switch")).toBeTruthy();
    expect(
      screen.queryByText("GAIA wrote this rule from your task"),
    ).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit rule" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { expanded: false }));

    expect(screen.getByRole("button", { expanded: true })).toBeTruthy();
    expect(screen.getByRole("list")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit rule" })).toBeTruthy();
  });

  it("says who wrote the rule and what it does", () => {
    renderPanel();

    expect(screen.getByText(BILLING)).toBeTruthy();
    expect(
      screen.getByText("GAIA wrote this rule from your task"),
    ).toBeTruthy();
    expect(screen.getByText(/skips the rest/)).toBeTruthy();
  });

  it("saves an edited rule, trimmed, only when the user saves it", () => {
    const { onConditionSave } = renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "Edit rule" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Runs only when" }), {
      target: { value: `  ${INVOICES} ` },
    });
    expect(onConditionSave).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save rule" }));

    expect(onConditionSave).toHaveBeenCalledWith(INVOICES);
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("drops the draft on cancel", () => {
    const { onConditionSave } = renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "Edit rule" }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: INVOICES },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onConditionSave).not.toHaveBeenCalled();
    expect(screen.getByText(BILLING)).toBeTruthy();
  });

  it("turns the rule off from its switch", () => {
    const { onEnabledChange } = renderPanel();

    fireEvent.click(screen.getByRole("switch"));

    expect(onEnabledChange).toHaveBeenCalledWith(false);
  });

  it("shows a system rule's wording without letting it be rewritten", () => {
    renderPanel({ condition: DESK_TEXT, editable: false, saved: DESK });

    expect(screen.getByText(DESK_TEXT)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Edit rule" })).toBeNull();
    expect(screen.getByRole("switch")).toBeTruthy();
  });

  it("lists the latest skips newest first", () => {
    renderPanel({ saved: saved({ recent_skips: [OLDER, NEWER] }) });

    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining(NEWER.event),
      expect.stringContaining(OLDER.event),
    ]);
  });

  it("describes an edited, unsaved rule as the user's, without the old rule's skips", () => {
    renderPanel({
      condition: INVOICES,
      saved: saved({ recent_skips: [NEWER] }),
    });

    expect(screen.getByText("You wrote this rule")).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("says nothing was skipped yet when the rule has skipped nothing", () => {
    renderPanel();

    expect(screen.getByText("Nothing skipped yet.")).toBeTruthy();
  });

  it("says a rule still being learned skips nothing, and lists no skips", () => {
    renderPanel({ saved: saved({ enforced: false, recent_skips: [NEWER] }) });

    expect(
      screen.getByText(
        "GAIA is still learning this rule, so every event runs for now.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("says a rule that is off lets every event run", () => {
    renderPanel({ enabled: false });

    expect(screen.getByText("Off, so every event runs.")).toBeTruthy();
  });

  it("offers to add a rule when there is none", () => {
    const { onConditionSave } = renderPanel({ condition: "", saved: null });

    expect(screen.getByText("Runs on every event")).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Add a rule" }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: INVOICES },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save rule" }));

    expect(onConditionSave).toHaveBeenCalledWith(INVOICES);
  });
});
