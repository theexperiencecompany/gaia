// @vitest-environment jsdom
/**
 * The wizard's browser-only steps reach the server, which stamps each once per
 * onboarding run and owns its event. The web never called POST
 * /onboarding/phase, so no step between the answers and the paywall was ever
 * counted, and onboarding:started fired from the client on every mount.
 */

import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const reportOnboardingStep = vi.fn();
const track = vi.fn();

vi.mock("@/features/onboarding/api/onboardingApi", () => ({
  reportOnboardingStep: (...args: unknown[]) => reportOnboardingStep(...args),
}));

vi.mock("@/lib/analytics", () => ({
  track: (...args: unknown[]) => track(...args),
}));

import { useOnboardingStepReports } from "@/features/onboarding/effects/useOnboardingStepReports";
import type { Stage } from "@/features/onboarding/state/types";

interface Props {
  stage: Stage;
  hydrated: boolean;
  known: boolean;
}

function renderReports(initialProps: Props) {
  return renderHook(
    ({ stage, hydrated, known }: Props) =>
      useOnboardingStepReports(stage, hydrated, known, false),
    { initialProps },
  );
}

const reported = () => reportOnboardingStep.mock.calls.map(([step]) => step);

beforeEach(() => {
  vi.clearAllMocks();
  reportOnboardingStep.mockResolvedValue({
    phase: "started",
    first_time: true,
  });
});

describe("onboarding step reports", () => {
  it("reports the start once per mount, only after the cache is restored", () => {
    const { rerender } = renderReports({
      stage: "questions",
      hydrated: false,
      known: true,
    });
    expect(reportOnboardingStep).not.toHaveBeenCalled();

    rerender({ stage: "questions", hydrated: true, known: true });
    rerender({ stage: "questions", hydrated: true, known: true });

    expect(reported()).toEqual(["started"]);
    expect(track).not.toHaveBeenCalled();
  });

  it("does not count a paying user parked on payment while the plan loads", () => {
    const { rerender } = renderReports({
      stage: "payment",
      hydrated: true,
      known: false,
    });
    expect(reported()).toEqual(["started"]);

    rerender({ stage: "paidReveal", hydrated: true, known: true });
    expect(reported()).toEqual(["started", "paid_reveal_seen"]);
  });

  it("reports the paywall once the plan is known to be unpaid", () => {
    renderReports({ stage: "payment", hydrated: true, known: true });
    expect(reported()).toEqual(["started", "paywall_reached"]);
  });
});
