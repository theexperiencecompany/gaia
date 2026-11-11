// @vitest-environment jsdom

import type { AuthoredGateView, SystemGateView } from "@shared/api/generated";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type React from "react";
import { describe, expect, it, vi } from "vitest";

import { GateRow } from "@/features/workflows/triggers/components/GateRow";

const BILLING = "the email is from a customer about billing";
const INVOICES = "the email is about an invoice";
const DESK_TEXT = "a real person or a real obligation is waiting on you";
const OLDER = {
  event: "Substack · Weekly digest",
  at: "2026-11-05T08:00:00Z",
  certainty: 0.94,
};
const NEWER = { event: "Uber · Your receipt", at: "2026-11-05T09:00:00Z" };

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
  skipped_count: 0,
  ...overrides,
});

const DESK: SystemGateView = {
  kind: "system",
  preset: "inbox_desk",
  display_condition: DESK_TEXT,
  enabled: true,
  enforced: true,
  recent_skips: [],
  skipped_count: 0,
};

const renderRow = (
  overrides: Partial<React.ComponentProps<typeof GateRow>> = {},
) => {
  const props = {
    condition: BILLING,
    enabled: true,
    saved: saved() as AuthoredGateView | SystemGateView | null,
    editable: true,
    watchesMail: true,
    onConditionSave: vi.fn(),
    onEnabledChange: vi.fn(),
    ...overrides,
  };
  render(<GateRow {...props} />);
  return props;
};

const row = () =>
  screen.getByRole("button", { name: /only when|checks|runs/i });
const openDetail = () => {
  fireEvent.click(row());
  return screen.getByRole("dialog");
};

describe("a job's rule row", () => {
  it("reads as the rule itself, as one sentence", () => {
    renderRow();

    expect(row().textContent).toContain(`Only when ${BILLING}`);
    expect(screen.queryByText(/runs only when/i)).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("counts what the rule skipped, and says nothing when it skipped nothing", () => {
    renderRow({
      saved: saved({ recent_skips: [OLDER, NEWER], skipped_count: 2 }),
    });
    expect(row().textContent).toContain("2 skipped");
  });

  it("counts every skip, not only the few it keeps to show", () => {
    renderRow({
      saved: saved({ recent_skips: [OLDER, NEWER], skipped_count: 40 }),
    });
    expect(row().textContent).toContain("40 skipped");
  });

  it("hides the count while there are no skips", () => {
    renderRow();
    expect(row().textContent).not.toMatch(/skipped/);
  });

  it("says it checks every email once the filter is off, with no count", () => {
    renderRow({
      enabled: false,
      saved: saved({ enabled: false, recent_skips: [OLDER] }),
    });

    expect(row().textContent).toContain("Checks every email");
    expect(row().textContent).not.toContain(BILLING);
    expect(row().textContent).not.toMatch(/skipped/);
  });

  it("says it runs on every event when an off filter is not on mail", () => {
    renderRow({ enabled: false, watchesMail: false });
    expect(row().textContent).toContain("Runs on every event");
  });

  it("is not there at all when the job has no rule", () => {
    const { container } = render(
      <GateRow
        condition=""
        enabled
        saved={null}
        editable
        watchesMail
        onConditionSave={vi.fn()}
        onEnabledChange={vi.fn()}
      />,
    );
    expect(container.textContent).toBe("");
  });
});

describe("a rule's detail", () => {
  it("lists the latest skips newest first, and opens one to say why", () => {
    renderRow({ saved: saved({ recent_skips: [OLDER, NEWER] }) });
    const detail = openDetail();

    const items = within(detail).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining(NEWER.event),
      expect.stringContaining(OLDER.event),
    ]);
    expect(within(detail).queryByText(/didn't match/i)).toBeNull();
    fireEvent.click(within(items[1]).getByRole("button"));
    expect(
      within(detail).getByText("Didn't match this rule, 94% sure"),
    ).toBeTruthy();
  });

  it("says nothing was skipped yet when it has skipped nothing", () => {
    renderRow();
    expect(within(openDetail()).getByText("Nothing skipped yet")).toBeTruthy();
  });

  it("turns the filter off from its switch", () => {
    const props = renderRow();
    const detail = openDetail();

    expect(
      within(detail).getByText("When off, GAIA looks at every email."),
    ).toBeTruthy();
    fireEvent.click(
      within(detail).getByRole("switch", { name: "Filter new mail" }),
    );
    expect(props.onEnabledChange).toHaveBeenCalledWith(false);
  });

  it("saves an edited rule, trimmed, only when the user saves it", () => {
    const props = renderRow();
    const detail = openDetail();

    fireEvent.click(within(detail).getByRole("button", { name: "Edit rule" }));
    fireEvent.change(within(detail).getByRole("textbox"), {
      target: { value: `  ${INVOICES} ` },
    });
    expect(props.onConditionSave).not.toHaveBeenCalled();
    fireEvent.click(within(detail).getByRole("button", { name: "Save" }));
    expect(props.onConditionSave).toHaveBeenCalledWith(INVOICES);
  });

  it("drops the draft on cancel", () => {
    const props = renderRow();
    const detail = openDetail();

    fireEvent.click(within(detail).getByRole("button", { name: "Edit rule" }));
    fireEvent.change(within(detail).getByRole("textbox"), {
      target: { value: INVOICES },
    });
    fireEvent.click(within(detail).getByRole("button", { name: "Cancel" }));
    expect(props.onConditionSave).not.toHaveBeenCalled();
    expect(within(detail).getByText(`Only when ${BILLING}`)).toBeTruthy();
  });

  it("says the user edited the rule only when they did", () => {
    renderRow({ saved: saved({ author: "user" }) });
    expect(within(openDetail()).getByText("Edited by you")).toBeTruthy();
  });

  it("names no author for a rule GAIA wrote", () => {
    renderRow();
    expect(within(openDetail()).queryByText("Edited by you")).toBeNull();
  });

  it("shows a system rule's wording without letting it be rewritten", () => {
    renderRow({ condition: DESK_TEXT, saved: DESK, editable: false });
    const detail = openDetail();

    expect(within(detail).getByText(`Only when ${DESK_TEXT}`)).toBeTruthy();
    expect(
      within(detail).queryByRole("button", { name: "Edit rule" }),
    ).toBeNull();
  });

  it("drops the saved rule's skips once its wording is changed and unsaved", () => {
    renderRow({ condition: INVOICES, saved: saved({ recent_skips: [OLDER] }) });
    expect(row().textContent).not.toMatch(/skipped/);
    expect(within(openDetail()).getByText("Nothing skipped yet")).toBeTruthy();
  });
});
