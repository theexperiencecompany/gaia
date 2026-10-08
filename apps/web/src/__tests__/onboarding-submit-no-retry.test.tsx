// @vitest-environment jsdom
/**
 * A failed onboarding submit must stay failed until the user asks again.
 * Before #1161 an effect re-POSTed /onboarding on every re-render after a 422,
 * 31k requests from one user (.agents/plans/posthog-audit/inflation.md).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const completeOnboarding = vi.fn();

vi.mock("@/features/auth/api/authApi", () => ({
  authApi: {
    completeOnboarding: (...args: unknown[]) => completeOnboarding(...args),
  },
}));

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ onboarding: { completed: false } }),
}));

import { useOnboardingSubmission } from "@/features/onboarding/hooks/useOnboardingSubmission";
import { initialState } from "@/features/onboarding/state/initial";
import type { OnboardingState } from "@/features/onboarding/state/types";

function answeredState(): OnboardingState {
  return {
    ...initialState,
    responses: { profession: "founder" },
    selectedNeeds: ["inbox"],
  };
}

function renderSubmission() {
  const queryClient = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(({ state }) => useOnboardingSubmission(state, vi.fn()), {
    initialProps: { state: answeredState() },
    wrapper,
  });
}

/** What the flow did after a failure: re-render with fresh state objects. */
async function rerenderSeveralTimes(
  rerender: (props: { state: OnboardingState }) => void,
): Promise<void> {
  for (let i = 0; i < 3; i++) {
    rerender({ state: answeredState() });
    await act(async () => {
      await Promise.resolve();
    });
  }
}

describe("onboarding submission", () => {
  beforeEach(() => {
    completeOnboarding.mockReset();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("never submits without a user action", async () => {
    const { rerender } = renderSubmission();

    await rerenderSeveralTimes(rerender);

    expect(completeOnboarding).not.toHaveBeenCalled();
  });

  it("does not re-submit after a failure when the flow re-renders", async () => {
    completeOnboarding.mockRejectedValue(new Error("422"));
    const { result, rerender } = renderSubmission();

    act(() => result.current.submit());
    await waitFor(() => expect(result.current.status).toBe("error"));
    await rerenderSeveralTimes(rerender);

    expect(completeOnboarding).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("error");
  });

  it("retries once when the user asks again", async () => {
    completeOnboarding.mockRejectedValueOnce(new Error("422"));
    completeOnboarding.mockResolvedValueOnce({ success: true });
    const { result } = renderSubmission();

    act(() => result.current.submit());
    await waitFor(() => expect(result.current.status).toBe("error"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.status).toBe("success"));

    expect(completeOnboarding).toHaveBeenCalledTimes(2);
  });
});
