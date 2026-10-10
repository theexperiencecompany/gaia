// @vitest-environment jsdom
/**
 * api:request_failed carries the API's machine code as `error_code` (the
 * Errors & Reliability tiles split 401/402 on it) and never the message.
 */
import { ApiError } from "@shared/api";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { track } from "@/lib/analytics";
import { reportFailure } from "@/lib/api/outcome";

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast: { error: vi.fn() } }));

const mockTrack = vi.mocked(track);

describe("reportFailure analytics", () => {
  beforeEach(() => {
    mockTrack.mockClear();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("sends the envelope's code, not its message", () => {
    const error = new ApiError(
      "Subscribe to keep going, alex@example.com",
      402,
      {
        envelope: {
          message: "Subscribe to keep going",
          code: "subscription_required",
        },
      },
    );

    reportFailure(
      "POST",
      "/chat-stream?q=secret",
      error,
      { silent: true },
      false,
    );

    expect(mockTrack).toHaveBeenCalledWith("api:request_failed", {
      method: "POST",
      url: "/chat-stream",
      status: 402,
      error_code: "subscription_required",
    });
  });

  it("sends no code for a transport failure, whose message is free text", () => {
    const error = new ApiError("timeout of 30000ms exceeded", 0);

    reportFailure("GET", "/todos", error, { silent: true }, false);

    expect(mockTrack).toHaveBeenCalledWith("api:request_failed", {
      method: "GET",
      url: "/todos",
      status: 0,
      error_code: undefined,
    });
  });
});
