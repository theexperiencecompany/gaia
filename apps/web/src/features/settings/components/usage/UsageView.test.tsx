// @vitest-environment jsdom

/** Regression: a payer at 100% of the monthly allowance saw only "100% used", with no word on what stops or until when. */
import type { UsageSummary } from "@shared/types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { UsageView } from "./UsageView";

function proSummary(monthlyPct: number, dailyPct = 10): UsageSummary {
  return {
    user_id: "u1",
    plan_type: "pro",
    primary_feature: "chat_messages",
    last_updated: "2026-10-28T07:00:00Z",
    features: {},
    budget: {
      daily: { percentage: dailyPct, reset_time: "2026-10-29T00:00:00Z" },
      monthly: { percentage: monthlyPct, reset_time: "2026-11-01T00:00:00Z" },
      per_request_token_ceiling: 5_000_000,
    },
  };
}

describe("UsageView hero", () => {
  it("says usage is paused until the reset when Pro's monthly allowance is used up", () => {
    render(
      <UsageView summary={proSummary(100)} history={[]} onUpgrade={vi.fn()} />,
    );

    expect(screen.getByText(/^Paused until /)).toBeTruthy();
    expect(
      screen.getByText(/Chat, workflows and tracked todos resume/),
    ).toBeTruthy();
    expect(screen.queryByText("of your monthly allowance used")).toBeNull();
  });

  it("warns before the cap what happens at 100%", () => {
    render(
      <UsageView summary={proSummary(82)} history={[]} onUpgrade={vi.fn()} />,
    );

    expect(
      screen.getByText(
        /At 100%, chat, workflows and tracked todos pause until/,
      ),
    ).toBeTruthy();
  });

  it("names the reset date under the cap", () => {
    render(
      <UsageView summary={proSummary(30)} history={[]} onUpgrade={vi.fn()} />,
    );

    expect(screen.getByText("of your monthly allowance used")).toBeTruthy();
    expect(screen.getByText(/^Resets /)).toBeTruthy();
  });
});
