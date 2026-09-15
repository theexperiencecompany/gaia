// @vitest-environment jsdom
/**
 * The floating panel's contract: it collapses to a header plus progress, that
 * collapse is persisted in both directions, and a collapsed panel reopens from
 * a click anywhere on it rather than only from the icon.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchFirstSteps = vi.fn();
const setCollapsed = vi.fn();
const push = vi.fn();
const appendToInput = vi.fn();
const trackEvent = vi.fn();
let pathname = "/c";

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

vi.mock("@/i18n/navigation", () => ({ usePathname: () => pathname }));

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

import { FirstStepsWidget } from "@/features/first-steps/components/FirstStepsWidget";
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

describe("FirstStepsWidget", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    pathname = "/c";
    fetchFirstSteps.mockResolvedValue(TWO_DONE);
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  const renderWidget = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <FirstStepsWidget />
      </QueryClientProvider>,
    );

  const progressBar = () => screen.getByRole("progressbar");

  // The collapse clips the rows with `grid-template-rows` and marks them
  // inert rather than unmounting them, so "hidden" means unreachable, not
  // absent from the DOM. Roles are the honest check: an inert subtree is out
  // of the accessibility tree, which is exactly what a user loses.
  const reachableSteps = () =>
    screen.queryAllByRole("button", { name: /^(Say hi|Connect|Link|Create)/ });

  it("shows no progress bar while expanded — the rows are the progress", async () => {
    renderWidget();
    await waitFor(() => expect(reachableSteps()).toHaveLength(4));

    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("trades the steps for a progress bar when collapsed", async () => {
    fetchFirstSteps.mockResolvedValue({ ...TWO_DONE, collapsed: true });
    renderWidget();
    await waitFor(() =>
      expect(screen.getByLabelText("Expand first steps")).toBeDefined(),
    );

    expect(progressBar().getAttribute("aria-valuenow")).toBe("2");
    expect(progressBar().getAttribute("aria-valuemax")).toBe("4");
    expect(screen.getByText("First steps")).toBeDefined();
    expect(reachableSteps()).toHaveLength(0);
  });

  it("reopens from a click anywhere on the collapsed panel", async () => {
    fetchFirstSteps.mockResolvedValue({ ...TWO_DONE, collapsed: true });
    setCollapsed.mockResolvedValue(TWO_DONE);
    renderWidget();

    const panel = await screen.findByLabelText("Expand first steps");
    // The whole panel is the control, not a 32px icon inside it.
    expect(panel.className).toContain("absolute inset-0");
    fireEvent.click(panel);

    await waitFor(() => expect(setCollapsed).toHaveBeenCalledWith(false));
    await waitFor(() => expect(reachableSteps()).toHaveLength(4));
  });

  it("collapses through the server and restores on failure", async () => {
    const { promise, reject } = Promise.withResolvers<never>();
    setCollapsed.mockReturnValue(promise);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByLabelText("Collapse first steps")).toBeDefined(),
    );

    fireEvent.click(screen.getByLabelText("Collapse first steps"));

    // Optimistic: the panel closes before the request resolves.
    await waitFor(() =>
      expect(screen.getByLabelText("Expand first steps")).toBeDefined(),
    );
    expect(setCollapsed).toHaveBeenCalledWith(true);

    reject(new Error("offline"));

    await waitFor(() =>
      expect(screen.getByLabelText("Collapse first steps")).toBeDefined(),
    );
    expect(reachableSteps()).toHaveLength(4);
  });

  it("stays out of the way on the routes that own the checklist themselves", async () => {
    pathname = "/dashboard";
    renderWidget();

    await waitFor(() => expect(fetchFirstSteps).toHaveBeenCalled());
    expect(screen.queryByText("First steps")).toBeNull();
  });
});
