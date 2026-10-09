// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScheduleBuilder } from "./ScheduleBuilder";

function renderBuilder(value: string) {
  const onChange = vi.fn();
  render(
    <ScheduleBuilder
      value={value}
      onChange={onChange}
      timezone="UTC"
      onTimezoneChange={vi.fn()}
    />,
  );
  return { onChange };
}

const cronInput = () =>
  screen.queryByRole<HTMLInputElement>("textbox", { name: "Cron expression" });

describe("ScheduleBuilder with a stored cron", () => {
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
});
