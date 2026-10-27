import { parseSubscriptionRequiredBody } from "@gaia/shared";
import { describe, expect, it, vi } from "vitest";
import { createSSEConnection } from "./sse-client";

const { opened } = vi.hoisted(() => ({
  opened: { headers: null as Record<string, string> | null },
}));

vi.mock("react-native-sse", () => ({
  default: class {
    constructor(_url: string, init: { headers: Record<string, string> }) {
      opened.headers = init.headers;
    }
    addEventListener = vi.fn();
    removeAllEventListeners = vi.fn();
    close = vi.fn();
  },
}));

vi.mock("@/features/auth/utils/auth-storage", () => ({
  getAuthToken: vi.fn(async () => "token-1"),
}));

describe("createSSEConnection", () => {
  it("tells the backend the stream comes from the mobile app", async () => {
    const controller = await createSSEConnection("/chat-stream", {
      onMessage: vi.fn(),
    });
    await vi.waitFor(() => expect(opened.headers).not.toBeNull());
    controller.abort();

    expect(opened.headers?.["X-Client-Type"]).toBe("mobile");
  });
});

/**
 * The mobile SSE transport hands back the 402's raw `responseText`, never a
 * parsed object — this is the narrowing that turns it into an offer the chat
 * UI can act on, instead of the transport error it used to be retried as.
 *
 * (Component-level rendering is not covered: apps/mobile's vitest config is
 * node-env and collects `*.test.ts` only, with no React Native test renderer.)
 */
describe("parseSubscriptionRequiredBody", () => {
  const body = JSON.stringify({
    code: "subscription_required",
    message: "GAIA is a paid product.",
    checkout_url: "https://checkout.dodo.test/abc",
    discount_code: "LAUNCH20",
  });

  it("extracts the offer from a 402 response body", () => {
    const detail = parseSubscriptionRequiredBody(body);

    expect(detail).toEqual({
      code: "subscription_required",
      message: "GAIA is a paid product.",
      checkout_url: "https://checkout.dodo.test/abc",
      discount_code: "LAUNCH20",
    });
  });

  it("keeps a null checkout_url rather than inventing one", () => {
    // The API deliberately sends no link when Dodo is unreachable; the block
    // still stands, and the UI decides what to do about the missing link.
    const detail = parseSubscriptionRequiredBody(
      JSON.stringify({
        code: "subscription_required",
        message: "GAIA is a paid product.",
        checkout_url: null,
        discount_code: null,
      }),
    );

    expect(detail?.checkout_url).toBeNull();
  });

  it("ignores a 402 body that is not the subscription_required shape", () => {
    expect(
      parseSubscriptionRequiredBody(
        JSON.stringify({ message: "Payment error" }),
      ),
    ).toBeUndefined();
    expect(
      parseSubscriptionRequiredBody(
        JSON.stringify({ code: "something_else", message: "x" }),
      ),
    ).toBeUndefined();
  });

  it("treats an unparseable or empty body as not-a-paywall", () => {
    expect(parseSubscriptionRequiredBody("<html>502</html>")).toBeUndefined();
    expect(parseSubscriptionRequiredBody("")).toBeUndefined();
    expect(parseSubscriptionRequiredBody(null)).toBeUndefined();
  });
});
