// @vitest-environment jsdom
/**
 * The onboarding funnel is only as good as the order its events arrive in.
 * Three things were wrong and each is pinned below:
 *   - `onboarding:started` fired on mount, a render before the persisted
 *     state was applied, so a resumed session always claimed `has_saved_state:
 *     false`;
 *   - the payment stage being cleared was reported only once the receipt had
 *     been acknowledged, and reaching the receipt itself was never reported;
 *   - a restart replayed the flow with every once-per-stage guard still shut,
 *     so the second run emitted no stage steps at all.
 */

import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const trackEvent = vi.fn();
const trackOnboardingStep = vi.fn();

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { ONBOARDING_STARTED: "onboarding:started" },
  trackEvent: (...args: unknown[]) => trackEvent(...args),
  trackOnboardingStep: (...args: unknown[]) => trackOnboardingStep(...args),
}));

import { FIELD_NAMES, questions } from "@/features/onboarding/constants";
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

/** Drives the hook the way the flow does: one render per state transition. */
function renderFunnel(hydrated = true) {
  const { rerender } = renderHook(
    ({ state }: { state: OnboardingState }) =>
      useOnboardingAnalytics(state, getStage(state, PAID), hydrated),
    { initialProps: { state: initialState } },
  );
  return {
    advance: (state: OnboardingState) => {
      rerender({ state });
      return state;
    },
  };
}

beforeEach(() => {
  trackEvent.mockClear();
  trackOnboardingStep.mockClear();
});

describe("onboarding analytics", () => {
  it("reports Q1 then Q2 in order, each with its question id", () => {
    const { advance } = renderFunnel();

    let state = advance(
      apply(initialState, {
        type: "answer",
        field: FIELD_NAMES.PROFESSION,
        value: "founder",
      }),
    );
    expect(trackOnboardingStep.mock.calls).toEqual([
      [1, FIELD_NAMES.PROFESSION, { question_id: questions[0].id }],
    ]);

    state = advance(
      apply(
        state,
        { type: "toggleNeed", value: "inbox" },
        { type: "submitNeeds" },
      ),
    );
    expect(trackOnboardingStep.mock.calls[1]).toEqual([
      2,
      FIELD_NAMES.NEEDS,
      { question_id: questions[1].id },
    ]);
    // Clearing Q2 lands a paid user on the receipt: the payment stage is done.
    expect(trackOnboardingStep.mock.calls[2]).toEqual([
      3,
      "payment",
      undefined,
    ]);
    expect(trackOnboardingStep).toHaveBeenCalledTimes(3);

    advance(apply(state, { type: "ackPaidReveal" }));
    expect(trackOnboardingStep.mock.calls[3]).toEqual([
      4,
      "paid_reveal",
      undefined,
    ]);
  });

  it("says which way the platform pick was cleared", () => {
    const { advance } = renderFunnel();
    const atPlatforms = apply(
      initialState,
      { type: "answer", field: FIELD_NAMES.PROFESSION, value: "founder" },
      { type: "toggleNeed", value: "inbox" },
      { type: "submitNeeds" },
      { type: "ackPaidReveal" },
    );
    advance(atPlatforms);
    trackOnboardingStep.mockClear();

    advance(
      apply(atPlatforms, { type: "platformConnected", platform: "telegram" }),
    );
    expect(trackOnboardingStep.mock.calls).toEqual([
      [5, "platform_pick", { connected: true, platform: "telegram" }],
    ]);
  });

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

  it("re-reports the stages after a restart", () => {
    const { advance } = renderFunnel();
    const finished = apply(
      initialState,
      { type: "answer", field: FIELD_NAMES.PROFESSION, value: "founder" },
      { type: "toggleNeed", value: "inbox" },
      { type: "submitNeeds" },
      { type: "ackPaidReveal" },
      { type: "skipPlatforms" },
    );
    advance(finished);

    const restarted = advance(
      apply(finished, { type: "restartStart" }, { type: "restartDone" }),
    );
    trackOnboardingStep.mockClear();

    advance(
      apply(restarted, {
        type: "answer",
        field: FIELD_NAMES.PROFESSION,
        value: "student",
      }),
    );
    expect(trackOnboardingStep.mock.calls).toEqual([
      [1, FIELD_NAMES.PROFESSION, { question_id: questions[0].id }],
    ]);
  });
});
