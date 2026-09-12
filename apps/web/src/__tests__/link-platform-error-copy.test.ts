// @vitest-environment jsdom
/**
 * What the platform-link page says when the link fails.
 *
 * The backend's `AppError` serialises `{ message, why, fix }` at the top level
 * of the response body — there is no `detail` wrapper — so the hook's own
 * `data.detail` read always found `undefined` and every failure degraded to
 * generic copy: a 409 lost the reason it was rejected, its `fix` never
 * reached the screen, and a 429 read "Failed to link account."
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
const get = vi.fn();

vi.mock("@tanstack/react-query", () => ({
  useIsRestoring: () => false,
}));

vi.mock("canvas-confetti", () => ({ default: vi.fn() }));

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));

vi.mock("@/lib/api/typed", () => ({
  api: {
    post: (...args: unknown[]) => post(...args),
    get: (...args: unknown[]) => get(...args),
  },
}));

vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { useLinkPlatform } from "@/features/auth/hooks/useLinkPlatform";

/** An axios rejection carrying the backend's structured error body. */
const apiError = (status: number, data: unknown) => ({
  response: { status, data },
});

async function link(rejection: unknown) {
  post.mockRejectedValue(rejection);
  const { result } = renderHook(() => useLinkPlatform("discord", "tok_1"));

  await act(async () => {
    await result.current.handleLink();
  });
  await waitFor(() => expect(result.current.error).not.toBeNull());

  return result.current.error;
}

describe("useLinkPlatform error copy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    get.mockResolvedValue({});
  });

  it("renders the backend's message and its fix on a 409", async () => {
    const error = await link(
      apiError(409, {
        message: "That Discord account is linked to another GAIA user.",
        why: "platform_link exists for this platform_user_id",
        fix: "Unlink it from the other account first, then try again.",
      }),
    );

    expect(error).toContain(
      "That Discord account is linked to another GAIA user.",
    );
    expect(error).toContain(
      "Unlink it from the other account first, then try again.",
    );
  });

  it("surfaces a rate-limit message instead of the generic failure", async () => {
    const error = await link(
      apiError(429, { message: "Too many link attempts. Wait a minute." }),
    );

    expect(error).toBe("Too many link attempts. Wait a minute.");
  });

  it("falls back to status copy when the body describes nothing", async () => {
    expect(await link(apiError(409, {}))).toBe(
      "This account is already linked.",
    );
  });
});
