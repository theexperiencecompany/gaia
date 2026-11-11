// @vitest-environment jsdom
import type { ReferralWorkflowMeter } from "@shared/api/generated";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { WorkflowMeterSection } from "./WorkflowMeterSection";

const meter = (
  overrides: Partial<ReferralWorkflowMeter>,
): ReferralWorkflowMeter => ({
  published: 1,
  subscribed: 0,
  per_month: 3,
  months_earned: 0,
  ...overrides,
});

afterEach(cleanup);

describe("From your workflows", () => {
  it("counts paying visitors toward the next free month", () => {
    render(<WorkflowMeterSection meter={meter({ subscribed: 2 })} />);

    expect(
      screen.getByText("2 of 3 subscribed. 1 more for a free month."),
    ).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
      "2",
    );
  });

  it("names the months a creator's workflows already earned", () => {
    render(
      <WorkflowMeterSection
        meter={meter({ subscribed: 1, months_earned: 2 })}
      />,
    );

    expect(screen.getByText("2 free months earned")).toBeTruthy();
    expect(
      screen.getByText("1 of 3 subscribed. 2 more for a free month."),
    ).toBeTruthy();
  });

  it("explains the meter to a creator who just published", () => {
    render(<WorkflowMeterSection meter={meter({})} />);

    expect(
      screen.getByText(
        "Every 3 people who start with your workflows and subscribe earn you a free month.",
      ),
    ).toBeTruthy();
  });

  it("shows nothing to someone with no community workflow and no credit", () => {
    const { container } = render(
      <WorkflowMeterSection meter={meter({ published: 0 })} />,
    );

    expect(container.textContent).toBe("");
  });
});
