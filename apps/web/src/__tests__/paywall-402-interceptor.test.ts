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

import { getSubscriptionRequiredDetail } from "@shared/types/subscription";
import { toast } from "@/lib/toast";
import { usePaywallModalStore } from "@/stores/paywallModalStore";
import { processAxiosError } from "@/utils/interceptorUtils";

describe("402 subscription_required handling", () => {
  beforeEach(() => {
    usePaywallModalStore.setState({ open: false, offer: null });
    vi.clearAllMocks();
  });

  it("extracts the subscription_required detail from a 402 body", () => {
    const detail = getSubscriptionRequiredDetail({
      detail: {
        code: "subscription_required",
        message: "Subscribe to keep chatting",
        checkout_url: "https://checkout.example/session",
        discount_code: "LAUNCH20",
      },
    });

    expect(detail).toEqual({
      code: "subscription_required",
      message: "Subscribe to keep chatting",
      checkout_url: "https://checkout.example/session",
      discount_code: "LAUNCH20",
    });
  });

  it("returns undefined for a body that isn't the subscription_required shape", () => {
    expect(
      getSubscriptionRequiredDetail({ detail: "Not found" }),
    ).toBeUndefined();
    expect(
      getSubscriptionRequiredDetail({ detail: { code: "other_code" } }),
    ).toBeUndefined();
  });

  it("opens the paywall modal with the 402 payload and marks the error handled", () => {
    const error = {
      response: {
        status: 402,
        data: {
          detail: {
            code: "subscription_required",
            message: "Subscribe to keep chatting",
            checkout_url: "https://checkout.example/session",
            discount_code: "LAUNCH20",
          },
        },
      },
    } as unknown as Parameters<typeof processAxiosError>[0];

    processAxiosError(error, { router: {} as never });

    const state = usePaywallModalStore.getState();
    expect(state.open).toBe(true);
    expect(state.offer).toEqual({
      checkoutUrl: "https://checkout.example/session",
      discountCode: "LAUNCH20",
      message: "Subscribe to keep chatting",
    });
    expect(error.handled).toBe(true);
  });

  it("suppresses the generic error toast for a 402 subscription_required response", () => {
    const error = {
      response: {
        status: 402,
        data: {
          detail: {
            code: "subscription_required",
            message: "Subscribe to keep chatting",
            checkout_url: null,
            discount_code: null,
          },
        },
      },
    } as unknown as Parameters<typeof processAxiosError>[0];

    processAxiosError(error, { router: {} as never });

    expect(toast.error).not.toHaveBeenCalled();
  });

  it("does not open the paywall for an unrelated 402-shaped body, and lets it fall through unhandled", () => {
    const error = {
      response: {
        status: 402,
        data: { detail: "Payment required" },
      },
    } as unknown as Parameters<typeof processAxiosError>[0];

    processAxiosError(error, { router: {} as never });

    expect(usePaywallModalStore.getState().open).toBe(false);
    // Not marking `handled` lets the caller's (service.ts) default error
    // handling show a toast instead of the request vanishing silently.
    expect(error.handled).toBe(false);
  });

  it("does not mark a malformed 402 body (no detail at all) as handled", () => {
    const error = {
      response: {
        status: 402,
        data: {},
      },
    } as unknown as Parameters<typeof processAxiosError>[0];

    processAxiosError(error, { router: {} as never });

    expect(usePaywallModalStore.getState().open).toBe(false);
    expect(error.handled).toBe(false);
  });
});

describe("chatApi chat-stream 402 handling (onopen)", () => {
  beforeEach(() => {
    usePaywallModalStore.setState({ open: false, offer: null });
    vi.clearAllMocks();
  });

  it("opens the paywall and throws a typed error for a 402 subscription_required response", async () => {
    vi.resetModules();
    let capturedOnOpen:
      | ((response: Response) => void | Promise<void>)
      | undefined;

    vi.doMock("@microsoft/fetch-event-source", () => ({
      fetchEventSource: vi.fn(
        async (_url: string, opts: Record<string, unknown>) => {
          capturedOnOpen = opts.onopen as typeof capturedOnOpen;
          // Simulate what the real library does: call onopen, let it throw.
          await (capturedOnOpen as (r: Response) => Promise<void>)(
            new Response(
              JSON.stringify({
                detail: {
                  code: "subscription_required",
                  message: "Subscribe to keep chatting",
                  checkout_url: "https://checkout.example/session",
                  discount_code: "LAUNCH20",
                },
              }),
              { status: 402 },
            ),
          );
        },
      ),
    }));
    vi.doMock("@/lib/api/service", () => ({ apiService: {} }));
    vi.doMock("@/lib/electron/api", () => ({
      desktopClientHeaders: () => ({}),
    }));
    vi.doMock("@/lib/streamLogger", () => ({
      streamLog: vi.fn(),
      streamLogError: vi.fn(),
    }));
    vi.doMock("@/lib/timezone", () => ({ getBrowserTimezone: () => "UTC" }));
    vi.doMock("@/stores/composerStore", () => ({
      useComposerStore: {
        getState: () => ({
          useDefaultModels: true,
          commsModel: null,
          executorModel: null,
        }),
      },
    }));

    const { chatApi, SubscriptionRequiredError } = await import(
      "@/features/chat/api/chatApi"
    );
    const { usePaywallModalStore: freshPaywallStore } = await import(
      "@/stores/paywallModalStore"
    );
    freshPaywallStore.setState({ open: false, offer: null });

    await expect(
      chatApi.fetchChatStream({
        inputText: "hi",
        history: [],
        conversationId: null,
        turnId: "turn-1",
        onMessage: () => undefined,
        onClose: () => {
          // No-op: this test only exercises the onopen 402 rejection path.
        },
        onError: () => {
          // No-op: this test only exercises the onopen 402 rejection path.
        },
        controller: new AbortController(),
        fileData: [],
        selectedTool: null,
        toolCategory: null,
        selectedWorkflow: null,
        selectedCalendarEvent: null,
        replyToMessage: null,
        isOnboardingDemo: false,
      }),
    ).rejects.toBeInstanceOf(SubscriptionRequiredError);

    const state = freshPaywallStore.getState();
    expect(state.open).toBe(true);
    expect(state.offer).toEqual({
      checkoutUrl: "https://checkout.example/session",
      discountCode: "LAUNCH20",
      message: "Subscribe to keep chatting",
    });

    vi.doUnmock("@microsoft/fetch-event-source");
    vi.doUnmock("@/lib/api/service");
    vi.doUnmock("@/lib/electron/api");
    vi.doUnmock("@/lib/streamLogger");
    vi.doUnmock("@/lib/timezone");
    vi.doUnmock("@/stores/composerStore");
    vi.resetModules();
  });
});
