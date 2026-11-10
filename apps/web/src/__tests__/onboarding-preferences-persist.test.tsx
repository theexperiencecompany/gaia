// @vitest-environment jsdom
/**
 * Q1 + Q2 have to reach the server before anything that reads them does.
 *
 * The server composes the platform opener ("Hi! I'm a founder. I could use
 * help with my inbox and my todos. Who are you?") from the stored profession
 * and needs. A failed save used to leave `preferencesPersisted` false with no
 * way to retry: the one-tap link code was never minted and the user went on
 * with their answers lost.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { isAxiosError } from "axios";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const saveOnboardingAnswers = vi.fn();

vi.mock("next-intl", () => ({ useLocale: () => "en" }));

vi.mock("@/features/onboarding/api/onboardingApi", () => ({
  saveOnboardingAnswers: (...args: unknown[]) => saveOnboardingAnswers(...args),
}));

import { FIELD_NAMES, questions } from "@/features/onboarding/constants";
import { useOnboardingPreferences } from "@/features/onboarding/effects/useOnboardingPreferences";
import { initialState } from "@/features/onboarding/state/initial";
import { reducer } from "@/features/onboarding/state/reducer";
import type { OnboardingState } from "@/features/onboarding/state/types";

const answered: OnboardingState = [
  { type: "answer", field: FIELD_NAMES.PROFESSION, value: "founder" } as const,
  { type: "toggleNeed", value: "inbox" } as const,
  { type: "toggleNeed", value: "tools" } as const,
  { type: "submitNeeds" } as const,
].reduce(reducer, initialState);

const badRequest = Object.assign(new Error("422"), {
  isAxiosError: true,
  response: { status: 422 },
});

function renderPersist(state: OnboardingState) {
  const dispatch = vi.fn();
  // Mutations retry immediately here; the policy under test is which errors retry.
  const client = new QueryClient({
    defaultOptions: { mutations: { retryDelay: 0 } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const view = renderHook(() => useOnboardingPreferences(state, dispatch), {
    wrapper,
  });
  return { ...view, dispatch };
}

describe("useOnboardingPreferences", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    saveOnboardingAnswers.mockResolvedValue({ success: true });
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    // A German browser on the never-localised /onboarding route, whose app locale is "en".
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["de-DE", "en-US"]);
  });

  it("does not save until both questions are answered", async () => {
    const afterQ1 = reducer(initialState, {
      type: "answer",
      field: FIELD_NAMES.PROFESSION,
      value: "founder",
    });
    expect(afterQ1.questionIndex).toBeLessThan(questions.length);

    renderPersist(afterQ1);
    await act(async () => Promise.resolve());

    expect(saveOnboardingAnswers).not.toHaveBeenCalled();
  });

  it("saves the exact profession and needs once, as soon as Q2 is confirmed", async () => {
    const { dispatch } = renderPersist(answered);

    await waitFor(() =>
      expect(dispatch).toHaveBeenCalledWith({ type: "preferencesPersisted" }),
    );
    expect(saveOnboardingAnswers).toHaveBeenCalledExactlyOnceWith({
      profession: "founder",
      needs: ["inbox", "tools"],
      language: "de-DE",
    });
  });

  it("does not re-send once the answers are already persisted", async () => {
    const { result } = renderPersist({
      ...answered,
      preferencesPersisted: true,
    });
    await act(async () => Promise.resolve());

    expect(saveOnboardingAnswers).not.toHaveBeenCalled();
    expect(result.current.status).toBe("success");
  });

  it("retries a dropped connection before giving up", async () => {
    saveOnboardingAnswers
      .mockRejectedValueOnce(new Error("Network Error"))
      .mockResolvedValueOnce({ success: true });

    const { dispatch } = renderPersist(answered);

    await waitFor(() =>
      expect(dispatch).toHaveBeenCalledWith({ type: "preferencesPersisted" }),
    );
    expect(saveOnboardingAnswers).toHaveBeenCalledTimes(2);
  });

  it("surfaces a failure that will not heal, and saves again only on the user's retry", async () => {
    expect(isAxiosError(badRequest)).toBe(true);
    saveOnboardingAnswers.mockRejectedValue(badRequest);

    const { result, dispatch } = renderPersist(answered);

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(saveOnboardingAnswers).toHaveBeenCalledTimes(1);
    expect(dispatch).not.toHaveBeenCalledWith({ type: "preferencesPersisted" });

    saveOnboardingAnswers.mockResolvedValue({ success: true });
    act(() => result.current.retry());

    await waitFor(() =>
      expect(dispatch).toHaveBeenCalledWith({ type: "preferencesPersisted" }),
    );
    expect(saveOnboardingAnswers).toHaveBeenCalledTimes(2);
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
