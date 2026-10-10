// @vitest-environment jsdom
/**
 * `onboarding:started` is the only client-owned onboarding event — step and
 * completion analytics live server-side (POST /onboarding/phase emits
 * onboarding:step_completed; the worker emits onboarding:completed), so the
 * hook must not re-emit them. It also fires post-hydration, so a resumed
 * session reports has_saved_state:true instead of always false.
 */

import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const trackEvent = vi.fn();

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { ONBOARDING_STARTED: "onboarding:started" },
  trackEvent: (...args: unknown[]) => trackEvent(...args),
}));

import { FIELD_NAMES } from "@/features/onboarding/constants";
import { useOnboardingAnalytics } from "@/features/onboarding/effects/useOnboardingAnalytics";
import { getStage } from "@/features/onboarding/state/derive";
import { initialState } from "@/features/onboarding/state/initial";
import { reducer } from "@/features/onboarding/state/reducer";
import type {
  Action,
  OnboardingState,
} from "@/features/onboarding/state/types";

const PAID = true;

function apply(state: OnboardingState, ...actions: Action[]): OnboardingState {
  return actions.reduce(reducer, state);
}

beforeEach(() => {
  trackEvent.mockClear();
});

describe("onboarding analytics", () => {
  it("fires onboarding:started once, and only with the restored state", () => {
    const resumed = apply(initialState, {
      type: "answer",
      field: FIELD_NAMES.PROFESSION,
      value: "founder",
    });

    const { rerender } = renderHook(
      ({ state, hydrated }: { state: OnboardingState; hydrated: boolean }) =>
        useOnboardingAnalytics(state, getStage(state, PAID), hydrated),
      { initialProps: { state: initialState, hydrated: false } },
    );
    expect(trackEvent).not.toHaveBeenCalled();

    rerender({ state: resumed, hydrated: true });
    expect(trackEvent.mock.calls).toEqual([
      ["onboarding:started", { has_saved_state: true }],
    ]);

    rerender({ state: resumed, hydrated: true });
    expect(trackEvent).toHaveBeenCalledTimes(1);
  });
});
