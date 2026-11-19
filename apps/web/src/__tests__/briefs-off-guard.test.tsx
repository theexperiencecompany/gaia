// @vitest-environment jsdom
//
// The real settings section, hook, typed client and ApiError run against an
// in-memory stand-in for the briefing-schedule endpoint that refuses "off"
// as the API does; only the axios transport is faked.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type * as ApiClient from "@/lib/api/client";

const request = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  apiauth: { request: (...args: unknown[]) => request(...args) },
  apiOrigin: "http://localhost:8000",
}));
vi.mock("@/lib/toast", () => ({
  toast: { error: (...args: unknown[]) => toastError(...args) },
}));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

import { BriefingScheduleSettings } from "@/features/settings/components/BriefingScheduleSettings";

const SCHEDULE_PATH = "/notifications/preferences/briefing-schedule";
const BRIEF_DELIVERY_WORKFLOWS_EXIST = "brief_delivery_workflows_exist";

interface StoredWorkflow {
  id: string;
  title: string;
  delivery: "now" | "brief" | "silent";
}

let schedule = { frequency: "daily", hour: 8 };
let workflows: StoredWorkflow[] = [];
const putBodies: Record<string, unknown>[] = [];

const ok = (data: unknown) => ({ status: 200, data, headers: {} });

const httpFailure = (status: number, data: unknown) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: {
      status,
      data,
      headers: { "content-type": "application/json" },
    },
  });

/** Mirrors set_briefing_schedule: "off" is a 409 while a workflow is left on the brief. */
const fakeApi = async (config: {
  method: string;
  url: string;
  data?: string;
}) => {
  if (config.url.endsWith("/user/quiet-hours")) {
    return ok({ enabled: false, start_hour: 22, end_hour: 8 });
  }
  if (!config.url.endsWith(SCHEDULE_PATH)) {
    throw new Error(`unexpected request ${config.method} ${config.url}`);
  }
  if (config.method === "GET") return ok(schedule);
  const body = JSON.parse(config.data ?? "{}");
  putBodies.push(body);
  const deliveries: Record<string, "now" | "silent"> =
    body.workflow_deliveries ?? {};
  if (body.frequency === "off") {
    const left = workflows.filter(
      (w) => w.delivery === "brief" && !deliveries[w.id],
    );
    if (left.length > 0) {
      throw httpFailure(409, {
        message: `${left.length} workflows send their results to your brief`,
        code: BRIEF_DELIVERY_WORKFLOWS_EXIST,
        workflows: left.map(({ id, title }) => ({ id, title })),
      });
    }
    workflows = workflows.map((w) =>
      deliveries[w.id] ? { ...w, delivery: deliveries[w.id] } : w,
    );
  }
  schedule = { frequency: body.frequency, hour: body.hour };
  return ok(schedule);
};

const renderSettings = () =>
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <BriefingScheduleSettings />
    </QueryClientProvider>,
  );

const frequencyTrigger = () =>
  screen.findByRole("button", { name: /Briefing frequency/ });

/** Open the frequency select the way a pointer does, then pick an option. */
const chooseFrequency = async (label: string) => {
  const trigger = await frequencyTrigger();
  await waitFor(() => expect(trigger.hasAttribute("disabled")).toBe(false));
  fireEvent.pointerDown(trigger, { pointerType: "mouse", button: 0 });
  fireEvent.pointerUp(trigger, { pointerType: "mouse", button: 0 });
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("option", { name: label }));
};

const chooseOff = () => chooseFrequency("Off");

const BLOCKED_DIALOG = { name: /send their results to your brief/ };

const dialog = () => screen.findByRole("dialog", BLOCKED_DIALOG);

describe("turning briefs off while workflows deliver to the brief", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    schedule = { frequency: "daily", hour: 8 };
    workflows = [
      { id: "wf_news", title: "Morning news", delivery: "brief" },
      { id: "wf_prs", title: "Open PRs", delivery: "brief" },
      { id: "wf_ping", title: "Deploy pings", delivery: "now" },
    ];
    putBodies.length = 0;
    request.mockImplementation(fakeApi);
  });

  it("is blocked: briefs stay on and the dialog names each brief workflow", async () => {
    renderSettings();

    await chooseOff();

    const modal = await dialog();
    expect(
      within(modal).getByText("2 workflows send their results to your brief"),
    ).toBeTruthy();
    expect(within(modal).getByText("Morning news")).toBeTruthy();
    expect(within(modal).getByText("Open PRs")).toBeTruthy();
    expect(within(modal).queryByText("Deploy pings")).toBeNull();
    expect(
      within(modal)
        .getByRole("button", { name: "Turn off briefs" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(schedule.frequency).toBe("daily");
    expect(toastError).not.toHaveBeenCalled();
  });

  it("turns briefs off once every workflow has a new delivery", async () => {
    renderSettings();
    await chooseOff();
    const modal = await dialog();

    fireEvent.click(
      within(modal).getByRole("button", { name: "Set all to Tell me now" }),
    );
    const prs = within(modal).getByRole("group", {
      name: "Delivery for Open PRs",
    });
    fireEvent.click(
      within(prs).getByRole("button", { name: "Don't notify me" }),
    );
    await act(async () => {
      fireEvent.click(
        within(modal).getByRole("button", { name: "Turn off briefs" }),
      );
    });

    await waitFor(() =>
      expect(screen.queryByRole("dialog", BLOCKED_DIALOG)).toBeNull(),
    );
    expect(schedule).toEqual({ frequency: "off", hour: 8 });
    expect(putBodies.at(-1)?.workflow_deliveries).toEqual({
      wf_news: "now",
      wf_prs: "silent",
    });
    expect(workflows.map((w) => w.delivery)).toEqual(["now", "silent", "now"]);
  });

  it("cancel leaves the schedule and every workflow as they were", async () => {
    renderSettings();
    await chooseOff();
    const modal = await dialog();

    fireEvent.click(
      within(modal).getByRole("button", { name: "Set all to Tell me now" }),
    );
    fireEvent.click(within(modal).getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", BLOCKED_DIALOG)).toBeNull(),
    );
    expect(putBodies).toHaveLength(1);
    expect(schedule.frequency).toBe("daily");
    expect(workflows.map((w) => w.delivery)).toEqual(["brief", "brief", "now"]);
    expect((await frequencyTrigger()).textContent).toContain("Every day");
  });

  it("turns briefs off at once when no workflow delivers to the brief", async () => {
    workflows = workflows.filter((w) => w.delivery !== "brief");
    renderSettings();

    await chooseOff();

    await waitFor(() => expect(schedule.frequency).toBe("off"));
    expect(screen.queryByRole("dialog", BLOCKED_DIALOG)).toBeNull();
  });
});
