import { parseSubscriptionRequiredBody } from "@gaia/shared";
import { describe, expect, it, vi } from "vitest";
import { EventStreamHttpError, readEventStream } from "./sse-client";

type Listener = (event: Record<string, unknown>) => void;

const { opened } = vi.hoisted(() => ({
  opened: {
    url: "",
    init: null as { method: string; headers: Record<string, string> } | null,
    listeners: new Map<string, Listener>(),
    closed: false,
  },
}));

vi.mock("react-native-sse", () => ({
  default: class {
    constructor(
      url: string,
      init: { method: string; headers: Record<string, string> },
    ) {
      opened.url = url;
      opened.init = init;
      opened.listeners = new Map();
      opened.closed = false;
    }
    addEventListener = (type: string, listener: Listener) => {
      opened.listeners.set(type, listener);
    };
    removeAllEventListeners = () => opened.listeners.clear();
    close = () => {
      opened.closed = true;
    };
  },
}));

vi.mock("@/features/auth/utils/auth-storage", () => ({
  getAuthToken: vi.fn(async () => "token-1"),
}));

const emit = (type: string, event: Record<string, unknown> = {}) =>
  opened.listeners.get(type)?.(event);

describe("readEventStream", () => {
  it("opens a GET stream that tells the backend it comes from the mobile app", async () => {
    const controller = new AbortController();
    const reading = readEventStream(
      "/c/events?after=3",
      vi.fn(),
      controller.signal,
    );
    await vi.waitFor(() => expect(opened.init).not.toBeNull());
    controller.abort();
    await reading;

    expect(opened.url).toMatch(/\/c\/events\?after=3$/);
    expect(opened.init?.method).toBe("GET");
    expect(opened.init?.headers["X-Client-Type"]).toBe("mobile");
    expect(opened.closed).toBe(true);
  });

  it("hands over each data payload and resolves when the server closes the stream", async () => {
    const onData = vi.fn();
    const reading = readEventStream("/e", onData, new AbortController().signal);
    await vi.waitFor(() => expect(opened.listeners.size).toBeGreaterThan(0));
    emit("message", { data: '{"frame":1}' });
    emit("message", { data: "" });
    emit("close");

    await expect(reading).resolves.toBeUndefined();
    expect(onData.mock.calls).toEqual([['{"frame":1}']]);
  });

  it("rejects with the status when the stream is refused", async () => {
    const reading = readEventStream(
      "/e",
      vi.fn(),
      new AbortController().signal,
    );
    await vi.waitFor(() => expect(opened.listeners.size).toBeGreaterThan(0));
    emit("error", { type: "error", xhrStatus: 404, message: "not found" });

    await expect(reading).rejects.toBeInstanceOf(EventStreamHttpError);
    await expect(reading).rejects.toMatchObject({ status: 404 });
  });
});

/**
 * A refused send hands back the 402's raw body text, never a parsed object;
 * this is the narrowing that turns it into an offer the chat UI can act on.
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
