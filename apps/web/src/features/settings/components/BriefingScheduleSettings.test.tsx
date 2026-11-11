// @vitest-environment jsdom
import type { BriefingSchedule } from "@gaia/shared/types";
import type { QuietHours } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { quietHoursApi } from "@/features/settings/api/quietHoursApi";
import { BriefingScheduleSettings } from "@/features/settings/components/BriefingScheduleSettings";
import { NotificationsAPI } from "@/services/api/notifications";

vi.mock("@/services/api/notifications", () => ({
  NotificationsAPI: {
    getBriefingSchedule: vi.fn(),
    updateBriefingSchedule: vi.fn(),
  },
}));

vi.mock("@/features/settings/api/quietHoursApi", () => ({
  quietHoursApi: { fetch: vi.fn(), update: vi.fn() },
}));

const NIGHT: QuietHours = { enabled: true, start_hour: 22, end_hour: 8 };

function renderSchedule(schedule: BriefingSchedule, quietHours: QuietHours) {
  vi.mocked(NotificationsAPI.getBriefingSchedule).mockResolvedValue(schedule);
  vi.mocked(quietHoursApi.fetch).mockResolvedValue(quietHours);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BriefingScheduleSettings />
    </QueryClientProvider>,
  );
}

const QUIET_NOTE = "Lands at 8 AM, when your quiet hours end.";

describe("the daily brief hour against quiet hours", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("says the brief lands when quiet hours end for an hour inside them", async () => {
    renderSchedule({ frequency: "daily", hour: 6 }, NIGHT);

    expect(await screen.findByText(QUIET_NOTE)).toBeTruthy();
  });

  it("counts the hour quiet hours start as inside them", async () => {
    renderSchedule({ frequency: "daily", hour: 22 }, NIGHT);

    expect(await screen.findByText(QUIET_NOTE)).toBeTruthy();
  });

  it("stays quiet for the hour quiet hours end", async () => {
    renderSchedule({ frequency: "daily", hour: 8 }, NIGHT);

    await screen.findAllByText("8 AM");
    expect(screen.queryByText(QUIET_NOTE)).toBeNull();
  });

  it("stays quiet when quiet hours are off", async () => {
    renderSchedule(
      { frequency: "daily", hour: 6 },
      { ...NIGHT, enabled: false },
    );

    await screen.findAllByText("6 AM");
    expect(screen.queryByText(QUIET_NOTE)).toBeNull();
  });

  it("stays quiet when there is no daily brief", async () => {
    renderSchedule({ frequency: "weekly_only", hour: 6 }, NIGHT);

    await screen.findAllByText("6 AM");
    expect(screen.queryByText(QUIET_NOTE)).toBeNull();
  });
});
