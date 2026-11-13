// @vitest-environment jsdom
/**
 * A failed onboarding submit must stay failed until the user asks again.
 * Before #1161 an effect re-POSTed /onboarding on every re-render after a 422,
 * 31k requests from one user (.agents/plans/posthog-audit/inflation.md).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
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

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

// The chat bubble's markdown and line choreography are not under test: which text it gets is.
vi.mock("@/features/onboarding/components/OnboardingBotBubble", () => ({
  OnboardingBotBubble: ({ text }: { text: string }) => <p>{text}</p>,
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
  usePathname: () => "/onboarding",
  useRouter: () => ({ push: vi.fn() }),
}));

import {
  Chat,
  ChatComposer,
} from "@/features/onboarding/components/stages/Chat";
import {
  FINISH_CTA_LABEL,
  FINISH_FAILED_MESSAGE,
  FINISH_RETRY_LABEL,
} from "@/features/onboarding/constants/messages";
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

/** The chat stage as the page mounts it: the bubble plus the composer button. */
function ChatStage() {
  const submission = useOnboardingSubmission(answeredState(), vi.fn());
  return (
    <>
      <Chat status={submission.status} />
      <ChatComposer submission={submission} />
    </>
  );
}

function renderChatStage() {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <ChatStage />
    </QueryClientProvider>,
  );
}

describe("onboarding chat stage", () => {
  beforeEach(() => {
    completeOnboarding.mockReset();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("offers Start chatting and sends nothing until it is clicked", () => {
    renderChatStage();

    expect(screen.getByRole("button", { name: FINISH_CTA_LABEL })).toBeTruthy();
    expect(completeOnboarding).not.toHaveBeenCalled();
  });

  it("hides the button while pending, then retries once from Try again", async () => {
    let rejectFirst: (error: Error) => void = () => undefined;
    completeOnboarding.mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectFirst = reject;
      }),
    );
    completeOnboarding.mockReturnValueOnce(new Promise(() => undefined));
    renderChatStage();

    fireEvent.click(screen.getByRole("button", { name: FINISH_CTA_LABEL }));
    await waitFor(() => expect(screen.queryByRole("button")).toBeNull());

    await act(async () => rejectFirst(new Error("422")));
    expect(await screen.findByText(FINISH_FAILED_MESSAGE)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: FINISH_RETRY_LABEL }));

    await waitFor(() => expect(completeOnboarding).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button")).toBeNull();
  });
});
