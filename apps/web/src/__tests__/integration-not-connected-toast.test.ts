import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/shared/RateLimitToast", () => ({
  showFeatureRestrictedToast: vi.fn(),
  showRateLimitToast: vi.fn(),
  showTokenLimitToast: vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
  toast: {
    error: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("@/stores/loginModalStore", () => ({
  useLoginModalStore: { getState: () => ({ openModal: vi.fn() }) },
}));

import { toast } from "@/lib/toast";
import { processAxiosError } from "@/utils/interceptorUtils";

interface ToastAction {
  label: string;
  onClick: () => void;
}

function forbidden(data: Record<string, unknown>) {
  return {
    response: { status: 403, data },
  } as unknown as Parameters<typeof processAxiosError>[0];
}

function pressToastAction(push: ReturnType<typeof vi.fn>): ToastAction {
  const options = vi.mocked(toast.error).mock.calls[0]?.[1] as {
    action: ToastAction;
  };
  options.action.onClick();
  expect(push).toHaveBeenCalledTimes(1);
  return options.action;
}

describe("403 INTEGRATION_NOT_CONNECTED toast", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // Regression: the calendar 403 toast's Reconnect only opened /integrations,
  // leaving the user to find Google Calendar and connect it themselves.
  it("starts that integration's connect flow when Reconnect is pressed", () => {
    const push = vi.fn();
    processAxiosError(
      forbidden({
        code: "INTEGRATION_NOT_CONNECTED",
        toolkit: "GOOGLECALENDAR",
        integration_id: "googlecalendar",
        message: "Reconnect Google Calendar to load your events.",
      }),
      { router: { push } as never },
    );

    expect(toast.error).toHaveBeenCalledWith(
      "Reconnect Google Calendar to load your events.",
      expect.objectContaining({ id: "integration-GOOGLECALENDAR" }),
    );
    expect(pressToastAction(push).label).toBe("Reconnect");
    expect(push).toHaveBeenCalledWith("/integrations?connect=googlecalendar");
  });

  it("falls back to the integrations page when the integration is unknown", () => {
    const push = vi.fn();
    processAxiosError(
      forbidden({ code: "INTEGRATION_NOT_CONNECTED", toolkit: "GMAIL" }),
      { router: { push } as never },
    );

    pressToastAction(push);
    expect(push).toHaveBeenCalledWith("/integrations");
  });
});
