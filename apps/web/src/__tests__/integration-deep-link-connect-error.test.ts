// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let search = "";
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
  useRouter: () => ({ replace }),
}));

import {
  type IntegrationDeepLinkHandlers,
  useIntegrationDeepLink,
} from "@/features/integrations/hooks/useIntegrationDeepLink";

function handlers(): IntegrationDeepLinkHandlers {
  return {
    onConnected: vi.fn(),
    onBearerRequired: vi.fn(),
    onFailed: vi.fn(),
    onOpen: vi.fn(),
    onConnectRequested: vi.fn(),
    onConnectLinkFailed: vi.fn(),
  };
}

describe("useIntegrationDeepLink connect_error", () => {
  beforeEach(() => {
    replace.mockClear();
  });

  it("reports a bounced connect link instead of landing silently", () => {
    search = "connect_error=invalid_or_expired_link";
    window.history.replaceState(null, "", `/integrations?${search}`);
    const h = handlers();

    renderHook(() => useIntegrationDeepLink(h));

    expect(h.onConnectLinkFailed).toHaveBeenCalledExactlyOnceWith(
      "invalid_or_expired_link",
    );
    expect(replace).toHaveBeenCalledWith("/integrations", { scroll: false });
    expect(h.onConnectRequested).not.toHaveBeenCalled();
  });
});

describe("useIntegrationDeepLink connect", () => {
  beforeEach(() => {
    replace.mockClear();
  });

  it("starts a reconnect of the account a notification names, once", () => {
    search = "connect=gmail&account=ca_work";
    window.history.replaceState(null, "", `/integrations?${search}`);
    const h = handlers();

    renderHook(() => useIntegrationDeepLink(h));

    expect(h.onConnectRequested).toHaveBeenCalledExactlyOnceWith(
      "gmail",
      "ca_work",
    );
    expect(replace).toHaveBeenCalledWith("/integrations", { scroll: false });
  });

  it("starts a plain connect when no account is named", () => {
    search = "connect=gmail";
    window.history.replaceState(null, "", `/integrations?${search}`);
    const h = handlers();

    renderHook(() => useIntegrationDeepLink(h));

    expect(h.onConnectRequested).toHaveBeenCalledExactlyOnceWith("gmail", null);
  });
});
