// @vitest-environment jsdom
import type { BriefingScheduleState } from "@gaia/shared/types";
import type { BriefingScheduleUpdate, QuietHours } from "@shared/api/generated";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  renderWithQueryClient,
  testQueryClient,
} from "@/__tests__/helpers/queryClient";
import { BriefingScheduleSettings } from "@/features/settings/components/BriefingScheduleSettings";
import { useBriefingScheduleSettings } from "@/features/settings/hooks/useBriefingScheduleSettings";
import { toast } from "@/lib/toast";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({
    isPaid: false,
    isUnknown: false,
    hasEverSubscribed: false,
  }),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const { getSchedule, putSchedule, getQuietHours } = vi.hoisted(() => ({
  getSchedule: vi.fn(),
  putSchedule: vi.fn(),
  getQuietHours: vi.fn(),
}));
vi.mock("@/lib/api/typed", () => ({
  api: {
    get: (path: string) =>
      path.endsWith("/quiet-hours") ? getQuietHours() : getSchedule(),
    put: (_path: string, init: { body: BriefingScheduleUpdate }) =>
      putSchedule(init.body),
  },
}));

const NIGHT: QuietHours = { enabled: true, start_hour: 22, end_hour: 8 };

type RunState = Pick<
  BriefingScheduleState,
  "paused_for_plan" | "next_daily_brief_at"
>;

function stored(
  schedule: Omit<BriefingScheduleState, keyof RunState>,
  runs: Partial<RunState> = {},
): BriefingScheduleState {
  return {
    ...schedule,
    paused_for_plan: false,
    next_daily_brief_at: null,
    ...runs,
  };
}

function renderSchedule(
  schedule: Omit<BriefingScheduleState, keyof RunState>,
  quietHours: QuietHours,
  runs: Partial<RunState> = {},
) {
  getSchedule.mockResolvedValue(stored(schedule, runs));
  getQuietHours.mockResolvedValue(quietHours);
  return renderWithQueryClient(<BriefingScheduleSettings />);
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

    expect(
      await screen.findByText("Next one Mon, Nov 16, 9:00 AM."),
    ).toBeTruthy();
  });

  it("names none while no daily brief runs", async () => {
    renderSchedule({ frequency: "daily", hour: 9 }, NIGHT);

    await screen.findAllByText("9 AM");
    expect(screen.queryByText(/^Next one/)).toBeNull();
  });
});

describe("saving the schedule", () => {
  const DAILY_AT_8 = stored({ frequency: "daily", hour: 8 });

  async function loaded() {
    const client = testQueryClient();
    const hook = renderHook(() => useBriefingScheduleSettings(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });
    await waitFor(() => expect(hook.result.current.schedule).not.toBeNull());
    return hook;
  }

  beforeEach(() => {
    vi.clearAllMocks();
    getSchedule.mockResolvedValue(DAILY_AT_8);
    putSchedule.mockImplementation((update: BriefingScheduleUpdate) =>
      Promise.resolve({ ...DAILY_AT_8, ...update }),
    );
  });

  it("saves a new frequency with the hour already set", async () => {
    const { result } = await loaded();

    act(() => result.current.update({ frequency: "weekdays" }));

    await waitFor(() =>
      expect(putSchedule).toHaveBeenCalledWith({
        frequency: "weekdays",
        hour: 8,
      }),
    );
    await waitFor(() =>
      expect(result.current.schedule?.frequency).toBe("weekdays"),
    );
  });

  it("does not call the server when nothing changed", async () => {
    const { result } = await loaded();

    act(() => result.current.update({ hour: 8 }));

    expect(putSchedule).not.toHaveBeenCalled();
  });

  it("rolls back a change the server refused", async () => {
    putSchedule.mockRejectedValue(new Error("500"));
    const { result } = await loaded();

    act(() => result.current.update({ frequency: "off" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(result.current.schedule).toEqual(DAILY_AT_8);
  });

  it("offers a retry when the schedule could not be read", async () => {
    getSchedule
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValue(DAILY_AT_8);
    getQuietHours.mockResolvedValue(NIGHT);
    renderWithQueryClient(<BriefingScheduleSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    expect((await screen.findAllByText("8 AM")).length).toBeGreaterThan(0);
  });
});
