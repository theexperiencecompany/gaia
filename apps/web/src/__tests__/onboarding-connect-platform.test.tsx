// @vitest-environment jsdom
/**
 * `useConnectPlatform` — the one seam between a platform button and the
 * one-tap linking handoff.
 *
 * What is pinned here: the minted code reaches every button (so nobody has to
 * type /auth), the mint failing still lets a user through on the old links,
 * and skipping hands the same composed message to the web chat as an
 * auto-send rather than dropping it in the composer.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, waitFor } from "@testing-library/react";
import { type ReactNode, StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mintLinkCode = vi.fn();
const apiPost = vi.fn();
const setPendingPrompt = vi.fn();

vi.mock("@/features/onboarding/api/onboardingApi", () => ({
  mintLinkCode: () => mintLinkCode(),
}));

vi.mock("@/lib/api/service", () => ({
  apiService: { post: (...args: unknown[]) => apiPost(...args) },
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock("@/stores/composerStore", () => ({
  useComposerStore: (selector: (s: unknown) => unknown) =>
    selector({ setPendingPrompt }),
}));

import { useConnectPlatform } from "@/features/onboarding/hooks/useConnectPlatform";

const CODE = "Ab3-_xY9zQ1234567890wE";
const FIRST_MESSAGE =
  "Hi! I'm a founder. I could use help with my inbox and my todos. Who are you?";
const MINTED = {
  code: CODE,
  first_message: FIRST_MESSAGE,
  handoff_text: `${FIRST_MESSAGE} #${CODE}`,
  links: {
    telegram: `https://t.me/heygaia_bot?start=${CODE}`,
    whatsapp: `https://wa.me/12762088737?text=encoded%20${CODE}`,
  },
};

/** Mirrors the hook's query key; the mint is cached under it, as in the app. */
const LINK_CODE_QUERY_KEY = ["onboarding", "platform-link-code"];

/** One client per test: the mint is cached per key, exactly as in the app. */
function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { Wrapper, queryClient };
}

/**
 * Renders the hook and waits for the mint to settle (resolved or failed), so
 * every test starts from the state the user actually sees: buttons wired to
 * the minted links. Waiting on the query state rather than a fixed number of
 * microtasks is what keeps this stable on a loaded CI box.
 */
async function renderConnect(dispatch = vi.fn()) {
  const { Wrapper, queryClient } = makeWrapper();
  const result = renderHook(() => useConnectPlatform(dispatch, true), {
    wrapper: Wrapper,
  });
  await waitFor(() => expect(mintLinkCode).toHaveBeenCalledOnce());
  await waitFor(() =>
    expect(queryClient.getQueryState(LINK_CODE_QUERY_KEY)?.status).not.toBe(
      "pending",
    ),
  );
  await act(async () => {
    await Promise.resolve();
  });
  return { ...result, dispatch };
}

describe("useConnectPlatform", () => {
  let openSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    mintLinkCode.mockResolvedValue(MINTED);
    openSpy = vi.fn();
    vi.stubGlobal("open", openSpy);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("mints one code on stage entry, not per button", async () => {
    const { result } = await renderConnect();

    act(() => result.current.connect("telegram"));
    act(() => result.current.connect("whatsapp"));

    expect(mintLinkCode).toHaveBeenCalledOnce();
  });

  // The server composes `first_message` from the stored profession + needs, so
  // a code minted before the PATCH lands says "Hi! Who are you?" instead of
  // "Hi! I'm a founder…" — on the web opener and every platform handoff.
  it("does not mint before the answers are persisted, and mints once after", async () => {
    const { rerender } = renderHook(
      ({ persisted }: { persisted: boolean }) =>
        useConnectPlatform(vi.fn(), persisted),
      { wrapper: makeWrapper().Wrapper, initialProps: { persisted: false } },
    );
    await act(async () => {
      await Promise.resolve();
    });

    expect(mintLinkCode).not.toHaveBeenCalled();

    rerender({ persisted: true });
    await waitFor(() => expect(mintLinkCode).toHaveBeenCalledOnce());
  });

  // The stage renders the hook twice — once for the picker, once for the
  // composer's "I'll do it later" — and React StrictMode double-invokes every
  // effect. That was four mints (and four dead codes) per stage entry.
  it("mints exactly once per stage entry across both hook users under StrictMode", async () => {
    function TwoConsumers() {
      useConnectPlatform(vi.fn(), true);
      useConnectPlatform(vi.fn(), true);
      return null;
    }
    const { Wrapper } = makeWrapper();

    render(
      <Wrapper>
        <StrictMode>
          <TwoConsumers />
        </StrictMode>
      </Wrapper>,
    );

    await waitFor(() => expect(mintLinkCode).toHaveBeenCalledOnce());
    await act(async () => {
      await Promise.resolve();
    });
    expect(mintLinkCode).toHaveBeenCalledOnce();
  });

  it("opens the code-carrying deep link for telegram", async () => {
    const { result, dispatch } = await renderConnect();

    act(() => result.current.connect("telegram"));

    expect(openSpy).toHaveBeenCalledWith(
      MINTED.links.telegram,
      "_blank",
      "noopener,noreferrer",
    );
    expect(dispatch).toHaveBeenCalledWith({
      type: "platformConnected",
      platform: "telegram",
    });
  });

  it("opens the code-carrying deep link for whatsapp", async () => {
    const { result } = await renderConnect();

    act(() => result.current.connect("whatsapp"));

    expect(openSpy.mock.calls[0][0]).toBe(MINTED.links.whatsapp);
  });

  it("falls back to the plain bot link when minting failed", async () => {
    mintLinkCode.mockRejectedValue(new Error("boom"));
    const { result } = await renderConnect();

    act(() => result.current.connect("telegram"));

    expect(openSpy.mock.calls[0][0]).toBe("https://t.me/heygaia_bot");
  });

  it("builds the iMessage sms: handoff from the registered contact number", async () => {
    apiPost.mockResolvedValue({
      auth_type: "manual",
      contact_number: "+15551234567",
      action_link: "https://photon.test/redirect",
    });
    const { result } = await renderConnect();

    act(() => result.current.connect("imessage"));
    expect(result.current.phoneModalOpen).toBe(true);
    expect(openSpy).not.toHaveBeenCalled();

    act(() => result.current.submitPhone("+15559999999"));
    await waitFor(() => expect(result.current.phoneTarget).not.toBeNull());

    expect(result.current.phoneTarget).toEqual({
      contactNumber: "+15551234567",
      command: MINTED.handoff_text,
      actionLink: `sms:+15551234567&body=${encodeURIComponent(MINTED.handoff_text)}`,
    });
  });

  it("keeps the /auth instructions for iMessage when minting failed", async () => {
    mintLinkCode.mockRejectedValue(new Error("boom"));
    apiPost.mockResolvedValue({
      auth_type: "manual",
      contact_number: "+15551234567",
      action_link: "https://photon.test/redirect",
    });
    const { result } = await renderConnect();

    act(() => result.current.submitPhone("+15559999999"));
    await waitFor(() => expect(result.current.phoneTarget).not.toBeNull());

    expect(result.current.phoneTarget).toEqual({
      contactNumber: "+15551234567",
      command: "/auth",
      actionLink: "https://photon.test/redirect",
    });
  });

  it("queues the composed first message for auto-send when platforms are skipped", async () => {
    const { result, dispatch } = await renderConnect();

    await act(async () => {
      await result.current.skip();
    });

    // `true` is the auto-send flag: the message must land as the user's own
    // turn, not sit unsent in the composer.
    expect(setPendingPrompt).toHaveBeenCalledWith(FIRST_MESSAGE, true);
    expect(dispatch).toHaveBeenCalledWith({ type: "skipPlatforms" });
  });

  it("still advances on skip when there is no code to send", async () => {
    mintLinkCode.mockRejectedValue(new Error("boom"));
    const { result, dispatch } = await renderConnect();

    await act(async () => {
      await result.current.skip();
    });

    expect(setPendingPrompt).not.toHaveBeenCalled();
    expect(dispatch).toHaveBeenCalledWith({ type: "skipPlatforms" });
  });
});
