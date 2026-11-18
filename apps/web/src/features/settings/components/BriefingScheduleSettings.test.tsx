// @vitest-environment jsdom
import type { BriefingScheduleState } from "@gaia/shared/types";
import type { QuietHours } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { briefingApi } from "@/features/briefing/api/briefingApi";
import { quietHoursApi } from "@/features/settings/api/quietHoursApi";
import { BriefingScheduleSettings } from "@/features/settings/components/BriefingScheduleSettings";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

vi.mock("@/features/briefing/api/briefingApi", () => ({
  briefingApi: {
    fetchSchedule: vi.fn(),
    updateSchedule: vi.fn(),
  },
}));

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({
    isPaid: false,
    isUnknown: false,
    hasEverSubscribed: false,
  }),
}));

vi.mock("@/features/settings/api/quietHoursApi", () => ({
  quietHoursApi: { fetch: vi.fn(), update: vi.fn() },
}));

const NIGHT: QuietHours = { enabled: true, start_hour: 22, end_hour: 8 };

type RunState = Pick<
  BriefingScheduleState,
  "paused_for_plan" | "next_daily_brief_at"
>;

function renderSchedule(
  stored: Pick<BriefingScheduleState, "frequency" | "hour">,
  quietHours: QuietHours,
  runs: Partial<RunState> = {},
) {
  const hasDailyBrief =
    stored.frequency === "daily" || stored.frequency === "weekdays";
  const schedule: BriefingScheduleState = {
    ...stored,
    paused_for_plan: false,
    next_daily_brief_at: null,
    has_daily_brief: hasDailyBrief,
    daily_brief_hour: hasDailyBrief ? (stored.hour ?? null) : null,
    ...runs,
  };
  vi.mocked(briefingApi.fetchSchedule).mockResolvedValue(schedule);
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

describe("a schedule that does not run without Pro", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUpgradeModalStore.getState().closeModal({ force: true });
  });

  it("says the briefs are paused and offers the upgrade", async () => {
    renderSchedule({ frequency: "daily", hour: 8 }, NIGHT, {
      paused_for_plan: true,
    });

    expect(await screen.findByText("Your briefs are paused")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Subscribe" }));

    const modal = useUpgradeModalStore.getState();
    expect([modal.open, modal.source, modal.dismissible]).toEqual([
      true,
      "settings_briefings",
      true,
    ]);
  });

  it("says nothing of the plan when the briefs run", async () => {
    renderSchedule({ frequency: "daily", hour: 8 }, NIGHT);

    await screen.findAllByText("8 AM");
    expect(screen.queryByText("Your briefs are paused")).toBeNull();
  });
});

describe("when the next daily brief lands", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("names the day and hour of the next one, on the reader's clock", async () => {
    const next = new Date(2026, 10, 16, 9, 0).toISOString();
    renderSchedule({ frequency: "daily", hour: 9 }, NIGHT, {
      next_daily_brief_at: next,
    });

    expect(await screen.findByText("Next one Mon 16 Nov, 9 AM.")).toBeTruthy();
  });

  it("names none while no daily brief runs", async () => {
    renderSchedule({ frequency: "daily", hour: 9 }, NIGHT);

    await screen.findAllByText("9 AM");
    expect(screen.queryByText(/^Next one/)).toBeNull();
  });
});
