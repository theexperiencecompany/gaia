// @vitest-environment jsdom
/**
 * api:request_failed counts real request failures: expected states are left
 * out, a repeat inside ten minutes is one failure, and only fixed codes leave
 * the browser, never a message.
 */
import { ApiError } from "@shared/api";
import { AxiosError } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { track } from "@/lib/analytics";
import { reportFailure, toApiError } from "@/lib/api/outcome";

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast: { error: vi.fn() } }));

const mockTrack = vi.mocked(track);
const TEN_MINUTES_MS = 10 * 60 * 1000;

const envelopeError = (status: number, code: string) =>
  new ApiError(`Something went wrong for alex@example.com (${code})`, status, {
    envelope: { message: "Something went wrong", code },
  });

const report = (url: string, error: ApiError) =>
  reportFailure("GET", url, error, { silent: true }, false);

describe("reportFailure analytics", () => {
  let now = Date.UTC(2026, 9, 8);

  beforeEach(() => {
    mockTrack.mockClear();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    // Each test moves the clock past the window, so no test inherits another's dedupe.
    now += 2 * TEN_MINUTES_MS;
    vi.spyOn(Date, "now").mockImplementation(() => now);
  });

  afterEach(() => vi.restoreAllMocks());

  it("sends the envelope's code, not its message", () => {
    reportFailure(
      "POST",
      "/chat-stream?q=secret",
      envelopeError(422, "validation_error"),
      { silent: true },
      false,
    );

    expect(mockTrack).toHaveBeenCalledWith("api:request_failed", {
      method: "POST",
      url: "/chat-stream",
      status: 422,
      error_code: "validation_error",
    });
  });

  it("leaves out a logged-out visitor's 401 and the paywall's 402", () => {
    report("/api/v1/user/me", envelopeError(401, "NOT_AUTHENTICATED"));
    report(
      "/api/v1/conversations",
      envelopeError(402, "subscription_required"),
    );

    expect(mockTrack).not.toHaveBeenCalled();
  });

  it("keeps a 401 that is not the logged-out state", () => {
    report("/api/v1/user/me", new ApiError("HTTP 401", 401));

    expect(mockTrack).toHaveBeenCalledTimes(1);
  });

  it("counts a repeat of the same failure once per ten minutes", () => {
    const failure = () =>
      report("/api/v1/onboarding", envelopeError(422, "validation_error"));

    failure();
    now += TEN_MINUTES_MS - 1;
    failure();
    now += 1;
    failure();

    expect(mockTrack).toHaveBeenCalledTimes(2);
  });

  it("counts a different status, url or code as its own failure", () => {
    report("/api/v1/onboarding", envelopeError(422, "validation_error"));
    report("/api/v1/onboarding", envelopeError(409, "validation_error"));
    report("/api/v1/todos", envelopeError(422, "validation_error"));
    report("/api/v1/onboarding", envelopeError(422, "conflict"));

    expect(mockTrack).toHaveBeenCalledTimes(4);
  });

  it.each([
    [AxiosError.ERR_NETWORK, "network"],
    [AxiosError.ECONNABORTED, "timeout"],
    [AxiosError.ETIMEDOUT, "timeout"],
    [AxiosError.ERR_CANCELED, "aborted"],
  ])("names a transport failure %s by a fixed code", (axiosCode, code) => {
    const error = toApiError(
      new AxiosError("timeout of 30000ms exceeded", axiosCode),
    );

    report("/api/v1/todos", error);

    expect(mockTrack).toHaveBeenCalledWith("api:request_failed", {
      method: "GET",
      url: "/api/v1/todos",
      status: 0,
      error_code: code,
    });
  });

  it("names a transport failure it cannot classify as unknown, never by its message", () => {
    report(
      "/api/v1/todos",
      toApiError(new Error("user typed alex@example.com")),
    );

    expect(mockTrack).toHaveBeenCalledWith("api:request_failed", {
      method: "GET",
      url: "/api/v1/todos",
      status: 0,
      error_code: "unknown",
    });
  });
});
