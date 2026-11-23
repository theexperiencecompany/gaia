// @vitest-environment jsdom

import { formatDate } from "@shared/utils";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RateLimitCard from "./RateLimitCard";

vi.mock("@/features/settings/hooks/useSetupStatus", () => ({
  useDeployment: () => ({ bills: true }),
}));

const TASK_SIZE_STOP =
  "This request hit its safety ceiling, so I'm stopping here with what I have so far. Try splitting the task into smaller steps.";

describe("RateLimitCard", () => {
  it("tells a pro user which wall bound instead of a generic daily count", () => {
    render(
      <RateLimitCard
        data={{
          feature: "task_size",
          current_plan: "pro",
          message: TASK_SIZE_STOP,
        }}
      />,
    );

    expect(screen.getByText(TASK_SIZE_STOP)).toBeDefined();
    expect(screen.queryByText(/calls\s+for today/)).toBeNull();
    expect(screen.queryByText(/Resets in/)).toBeNull();
  });

  it("names the day a monthly pause lifts instead of counting hundreds of hours", () => {
    const reset = new Date(Date.now() + 20 * 24 * 60 * 60 * 1000).toISOString();
    render(
      <RateLimitCard
        data={{
          feature: "monthly_usage",
          current_plan: "pro",
          reset_time: reset,
          message: "You've used this month's AI usage allowance.",
        }}
      />,
    );

    expect(screen.getByText(`Resets on ${formatDate(reset)}`)).toBeDefined();
    expect(screen.queryByText(/hours/)).toBeNull();
  });

  it("falls back to the daily-count copy when the backend sends no message", () => {
    render(
      <RateLimitCard
        data={{ feature: "chat_messages", current_plan: "pro" }}
      />,
    );

    expect(screen.getByText(/calls\s+for today/)).toBeDefined();
  });
});
