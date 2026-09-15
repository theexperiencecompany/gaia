// @vitest-environment jsdom
/**
 * Q1 + Q2 have to reach the server before anything that reads them does.
 *
 * The server composes the platform opener ("Hi! I'm a founder. I could use
 * help with my inbox and my todos. Who are you?") from the stored profession
 * and needs. Those were only written by the final `POST /onboarding`, which
 * runs at the very end of the flow — so the link code minted on the platform
 * stage was composed from nulls and every handoff read "Hi! Who are you?".
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const saveOnboardingPreferences = vi.fn();
const toastError = vi.fn();

vi.mock("@/features/onboarding/api/onboardingApi", () => ({
  saveOnboardingPreferences: (...args: unknown[]) =>
    saveOnboardingPreferences(...args),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: (...args: unknown[]) => toastError(...args) },
}));

import { FIELD_NAMES, questions } from "@/features/onboarding/constants";
import { useOnboardingPreferences } from "@/features/onboarding/effects/useOnboardingPreferences";
import { initialState } from "@/features/onboarding/state/initial";
import { reducer } from "@/features/onboarding/state/reducer";
import type { OnboardingState } from "@/features/onboarding/state/types";

const answered: OnboardingState = [
  { type: "answer", field: FIELD_NAMES.PROFESSION, value: "founder" } as const,
  { type: "toggleNeed", value: "inbox" } as const,
  { type: "toggleNeed", value: "todos" } as const,
  { type: "submitNeeds" } as const,
].reduce(reducer, initialState);

async function renderPersist(state: OnboardingState) {
  const dispatch = vi.fn();
  const view = renderHook(() => useOnboardingPreferences(state, dispatch));
  await act(async () => {
    await Promise.resolve();
  });
  return { ...view, dispatch };
}

describe("useOnboardingPreferences", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    saveOnboardingPreferences.mockResolvedValue({ success: true });
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("does not persist until both questions are answered", async () => {
    const afterQ1 = reducer(initialState, {
      type: "answer",
      field: FIELD_NAMES.PROFESSION,
      value: "founder",
    });
    expect(afterQ1.questionIndex).toBeLessThan(questions.length);

    await renderPersist(afterQ1);

    expect(saveOnboardingPreferences).not.toHaveBeenCalled();
  });

  it("PATCHes the exact profession and needs as soon as Q2 is confirmed", async () => {
    const { dispatch } = await renderPersist(answered);

    expect(saveOnboardingPreferences).toHaveBeenCalledExactlyOnceWith({
      profession: "founder",
      needs: ["inbox", "todos"],
    });
    await waitFor(() =>
      expect(dispatch).toHaveBeenCalledWith({ type: "preferencesPersisted" }),
    );
  });

  it("does not re-send once the answers are already persisted", async () => {
    await renderPersist({ ...answered, preferencesPersisted: true });

    expect(saveOnboardingPreferences).not.toHaveBeenCalled();
  });

  it("fails loud when the PATCH fails, and never marks the answers persisted", async () => {
    saveOnboardingPreferences.mockRejectedValue(new Error("boom"));

    const { dispatch } = await renderPersist(answered);

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(dispatch).not.toHaveBeenCalledWith({ type: "preferencesPersisted" });
  });
});

describe("preferencesPersisted state", () => {
  it("starts false and is only set by the persist action", () => {
    expect(initialState.preferencesPersisted).toBe(false);
    expect(answered.preferencesPersisted).toBe(false);
    expect(
      reducer(answered, { type: "preferencesPersisted" }).preferencesPersisted,
    ).toBe(true);
  });
});
