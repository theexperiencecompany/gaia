// @vitest-environment jsdom
/**
 * The CLI connect poll loop.
 *
 * Connecting a CLI is the only connect flow the client drives itself: it
 * re-POSTs an idempotent endpoint until the install finishes and the user has
 * approved a login. Three things about that loop are load-bearing and none are
 * visible from reading a single render:
 *
 *   - it must stop on a terminal phase, or it hammers a sandbox whose commands
 *     are serialised per user and starves their other tool calls;
 *   - it must stop when abandoned (unmount), or a response from a dead run
 *     overwrites the live one;
 *   - it must give up eventually, because the server will happily restart an
 *     expired device login forever.
 *
 * The poll interval is mocked down to a millisecond rather than driven with
 * fake timers: `waitFor` polls on real timers, and pinning React's `act` against
 * a faked clock deadlocks the two.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const postConnect = vi.fn();

vi.mock("@/features/integrations/api/integrationsApi", () => ({
  integrationsApi: {
    postConnect: (...args: unknown[]) => postConnect(...args),
  },
}));
vi.mock("@/features/integrations/api/queryKeys", () => ({
  integrationKeys: { all: ["integrations"] },
  toolKeys: { all: ["tools"] },
}));
// Literals, not constants: vi.mock factories are hoisted above every
// top-level binding in this file.
vi.mock("@/features/integrations/constants/connect", () => ({
  CLI_CONNECT_POLL_INTERVAL_MS: 1,
  CLI_CONNECT_POLL_MAX_ATTEMPTS: 5,
}));
vi.mock("@/lib/url-safety", () => ({
  sanitizeRedirectUrl: (url: string) => url,
}));
// A STABLE client: react-query returns one instance for the tree, and the
// poll callback depends on it. Handing back a fresh object per render would
// invalidate that callback every render and restart the loop forever, which is
// a defect in the mock, not in the hook. vi.hoisted so the binding exists by
// the time the hoisted factory below runs.
const { queryClient } = vi.hoisted(() => ({
  queryClient: { invalidateQueries: () => undefined },
}));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => queryClient,
}));

import { CLI_CONNECT_POLL_MAX_ATTEMPTS } from "@/features/integrations/constants/connect";
import { useCliConnect } from "@/features/integrations/hooks/useCliConnect";

const pending = (phase: string, instructions: string | null = null) => ({
  status: "pending",
  integrationId: "stripe_link",
  name: "Stripe Link",
  cli: { phase, instructions },
});

const connected = () => ({
  status: "connected",
  integrationId: "stripe_link",
  name: "Stripe Link",
  cli: { phase: "connected" },
});

/** Give the loop room to tick several more times if it is going to. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 40));

describe("useCliConnect", () => {
  beforeEach(() => {
    postConnect.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const render = (onConnected = vi.fn()) =>
    renderHook(() =>
      useCliConnect({
        integrationId: "stripe_link",
        isOpen: true,
        onConnected,
      }),
    );

  it("keeps polling while the install is running", async () => {
    postConnect.mockResolvedValue(pending("installing"));
    render();
    await waitFor(() =>
      expect(postConnect.mock.calls.length).toBeGreaterThan(2),
    );
  });

  it("stops the moment the connection lands", async () => {
    const onConnected = vi.fn();
    postConnect.mockResolvedValue(connected());
    render(onConnected);

    await waitFor(() =>
      expect(onConnected).toHaveBeenCalledWith("Stripe Link"),
    );
    const settled = postConnect.mock.calls.length;
    await settle();
    expect(postConnect.mock.calls.length).toBe(settled);
  });

  it("stops when the CLI asks for a token, instead of spinning on the prompt", async () => {
    postConnect.mockResolvedValue(pending("needs_token"));
    const { result } = render();

    await waitFor(() => expect(result.current.state.phase).toBe("needs_token"));
    const settled = postConnect.mock.calls.length;
    await settle();
    expect(postConnect.mock.calls.length).toBe(settled);
  });

  it("stops polling once unmounted", async () => {
    postConnect.mockResolvedValue(pending("awaiting_approval", "approve here"));
    const { unmount } = render();

    await waitFor(() => expect(postConnect).toHaveBeenCalled());
    unmount();
    const settled = postConnect.mock.calls.length;
    await settle();
    // One in-flight response may still land; the loop must not schedule more.
    expect(postConnect.mock.calls.length).toBeLessThanOrEqual(settled + 1);
  });

  it("gives up rather than polling an expired login forever", async () => {
    postConnect.mockResolvedValue(pending("awaiting_approval", "approve here"));
    const { result } = render();

    await waitFor(() => expect(result.current.state.phase).toBe("failed"));
    expect(postConnect.mock.calls.length).toBeLessThanOrEqual(
      CLI_CONNECT_POLL_MAX_ATTEMPTS,
    );
    expect(result.current.state.error).toContain("took too long");
  });

  it("surfaces a request failure instead of retrying blindly", async () => {
    postConnect.mockRejectedValue(new Error("network down"));
    const { result } = render();

    await waitFor(() => expect(result.current.state.phase).toBe("failed"));
    expect(result.current.state.error).toContain("network down");
    const settled = postConnect.mock.calls.length;
    await settle();
    expect(postConnect.mock.calls.length).toBe(settled);
  });

  it("exposes the approval link pulled out of the CLI's own output", async () => {
    postConnect.mockResolvedValue(
      pending(
        "awaiting_approval",
        'verification_url: "https://app.link.com/device/setup?code=abc-def"',
      ),
    );
    const { result } = render();

    await waitFor(() =>
      expect(result.current.state.approvalUrl).toBe(
        "https://app.link.com/device/setup?code=abc-def",
      ),
    );
  });
});
