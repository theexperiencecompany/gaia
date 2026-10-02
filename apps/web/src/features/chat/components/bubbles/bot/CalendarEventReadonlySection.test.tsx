// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CalendarOptions } from "@/types/features/calendarTypes";

import { CalendarEventReadonlySection } from "./CalendarEventReadonlySection";

const event: CalendarOptions = {
  summary: "Quarterly review",
  description: "Go over the numbers",
  start: "2026-02-02T10:00:00-05:00",
  end: "2026-02-02T11:00:00-05:00",
  calendar_name: "Work",
  attendees: ["a@x.com", "b@x.com"],
};

describe("CalendarEventReadonlySection", () => {
  it("renders stored event details for a restored legacy conversation", () => {
    render(<CalendarEventReadonlySection calendar_options={[event]} />);

    expect(screen.getByText("Quarterly review")).toBeDefined();
    expect(screen.getByText("Go over the numbers")).toBeDefined();
    // Timezone-safe: formatTimeRange always renders a dash-joined range for a
    // timed event, whatever the runner's zone.
    expect(screen.getByText((text) => text.includes("–"))).toBeDefined();
    expect(screen.getByText("Work")).toBeDefined();
    expect(screen.getByText("2 guests")).toBeDefined();
  });

  it("is read-only — no confirm or add action", () => {
    render(<CalendarEventReadonlySection calendar_options={[event]} />);

    expect(screen.queryByRole("button", { name: /confirm|add/i })).toBeNull();
  });

  it("renders nothing when no option carries a summary", () => {
    const { container } = render(
      <CalendarEventReadonlySection
        calendar_options={[{ summary: "" } as CalendarOptions]}
      />,
    );

    expect(container.firstChild).toBeNull();
  });
});
