// @vitest-environment jsdom
/**
 * The checklist's contract: rows mirror server state and are actions, not
 * toggles; the chevron persists the collapse in both directions.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchFirstSteps = vi.fn();
const setCollapsed = vi.fn();
const push = vi.fn();
const appendToInput = vi.fn();
const trackEvent = vi.fn();
let pathname = "/dashboard";

vi.mock("@/features/first-steps/api/firstStepsApi", () => ({
  firstStepsApi: {
    fetch: () => fetchFirstSteps(),
    setCollapsed: (collapsed: boolean) => setCollapsed(collapsed),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => pathname,
}));

vi.mock("@/stores/composerStore", () => ({
  useAppendToInput: () => appendToInput,
}));

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { FIRST_STEPS_STEP_CLICKED: "first_steps:step_clicked" },
  trackEvent: (...args: unknown[]) => trackEvent(...args),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { FirstStepsCard } from "@/features/first-steps/components/FirstStepsCard";
import { SAY_HI_PROMPT } from "@/features/first-steps/constants";
import type { FirstStepsResponse } from "@/types/features/firstStepsTypes";

const TWO_DONE: FirstStepsResponse = {
  collapsed: false,
  steps: [
    { key: "say_hi", done: true },
    { key: "connect_integration", done: true },
    { key: "link_platform", done: false },
    { key: "create_workflow", done: false },
  ],
};

describe("FirstStepsCard", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    pathname = "/dashboard";
    fetchFirstSteps.mockResolvedValue(TWO_DONE);
    setCollapsed.mockResolvedValue({ ...TWO_DONE, collapsed: true });
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  const renderCard = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <FirstStepsCard />
      </QueryClientProvider>,
    );

  // The row's accessible name is its label *and* its description: a screen
  // reader should hear what the step is for, not just its title.
  const step = (label: string) =>
    screen.getByRole("button", { name: new RegExp(`^${label}`) });

  it("renders every step as an action, not a toggle", async () => {
    renderCard();
    await waitFor(() => expect(step("Say hi")).toBeDefined());

    // A checkbox role would promise a toggle the server never honours.
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    // The card is in the page flow, so it carries no collapse control — only
    // the four step rows.
    expect(screen.getAllByRole("button")).toHaveLength(TWO_DONE.steps.length);
  });

  it("runs the step's action on a click anywhere in the row", async () => {
    renderCard();
    await waitFor(() => expect(step("Connect an integration")).toBeDefined());

    // The description, not the label: the whole row is one hit target.
    fireEvent.click(screen.getByText("Add Gmail, Calendar or Notion"));

    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith("/integrations");
    expect(trackEvent).toHaveBeenCalledWith("first_steps:step_clicked", {
      step: "connect_integration",
      done: true,
      surface: "dashboard",
    });
  });

  it("pre-fills the composer for the say-hi step", async () => {
    renderCard();
    await waitFor(() => expect(step("Say hi")).toBeDefined());

    fireEvent.click(screen.getByText("Say hi"));

    expect(appendToInput).toHaveBeenCalledWith(SAY_HI_PROMPT);
    // `appendToInput` owns the hop to /c; a router push here would be a
    // second navigation for one click.
    expect(push).not.toHaveBeenCalled();
  });

  it("refetches when the user navigates to another route", async () => {
    const { rerender } = renderCard();
    await waitFor(() => expect(fetchFirstSteps).toHaveBeenCalledTimes(1));

    // A step is completed by visiting another page, so arriving there is the
    // signal that the server-derived checklist may have changed.
    pathname = "/integrations";
    rerender(
      <QueryClientProvider client={queryClient}>
        <FirstStepsCard />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(fetchFirstSteps).toHaveBeenCalledTimes(2));
  });

  it("stays hidden once every step is done", async () => {
    fetchFirstSteps.mockResolvedValue({
      collapsed: false,
      steps: TWO_DONE.steps.map((s) => ({ ...s, done: true })),
    });
    renderCard();

    await waitFor(() => expect(fetchFirstSteps).toHaveBeenCalled());
    expect(screen.queryByText("First steps")).toBeNull();
  });
});
