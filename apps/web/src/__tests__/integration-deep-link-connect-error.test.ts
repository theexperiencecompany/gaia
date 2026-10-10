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
