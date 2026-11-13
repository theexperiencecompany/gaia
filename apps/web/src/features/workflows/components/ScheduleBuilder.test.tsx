// @vitest-environment jsdom
import type { CronValidationResponse } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScheduleBuilder } from "./ScheduleBuilder";

const TOO_FREQUENT = "Schedules can repeat at most once an hour.";

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/api/typed", () => ({ api: { get: apiGet } }));

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    {children}
  </QueryClientProvider>
);

function renderBuilder(value: string) {
  const onChange = vi.fn();
  render(
    <ScheduleBuilder
      value={value}
      onChange={onChange}
      timezone="UTC"
      onTimezoneChange={vi.fn()}
    />,
    { wrapper },
  );
  return { onChange };
}

const cronInput = () =>
  screen.queryByRole<HTMLInputElement>("textbox", { name: "Cron expression" });

describe("ScheduleBuilder with a stored cron", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiGet.mockImplementation(
      async (
        _path: string,
        { query }: { query: { expression: string } },
      ): Promise<CronValidationResponse> => ({
        expression: query.expression,
        valid: true,
      }),
    );
  });

  it("opens a yearly cron in custom mode showing the exact expression", () => {
    renderBuilder("0 9 1 1 *");

    expect(cronInput()?.value).toBe("0 9 1 1 *");
  });

  it("opens a step cron in custom mode showing the exact expression", () => {
    renderBuilder("*/15 * * * *");

    expect(cronInput()?.value).toBe("*/15 * * * *");
  });

  it("leaves a yearly cron untouched when opened and not edited", () => {
    const { onChange } = renderBuilder("0 9 1 1 *");

    expect(onChange).not.toHaveBeenCalled();
    expect(cronInput()?.value).toBe("0 9 1 1 *");
  });

  it.each([
    ["daily", "30 8 * * *", "Day"],
    ["weekly", "0 9 * * 3", "Week"],
    ["monthly", "0 9 15 * *", "Month"],
  ])("opens a %s cron as a preset", (_kind, cron, intervalLabel) => {
    renderBuilder(cron);

    expect(cronInput()).toBeNull();
    const intervalSelect = screen.getByRole("button", {
      name: /Select day or week or month/,
    });
    expect(intervalSelect.textContent).toContain(intervalLabel);
  });

  it("shows the server's reason when it refuses a stored step cron", async () => {
    const verdict: CronValidationResponse = {
      expression: "*/15 * * * *",
      valid: false,
      error: TOO_FREQUENT,
    };
    apiGet.mockResolvedValue(verdict);

    renderBuilder("*/15 * * * *");

    expect(await screen.findByText(TOO_FREQUENT)).toBeTruthy();
    expect(cronInput()?.value).toBe("*/15 * * * *");
  });
});
