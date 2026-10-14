// @vitest-environment jsdom
/** Hosted GAIA mounts no /setup routes: no surface may probe them, or every login 404s and toasts. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { replace, fetchSetupStatus, fetchCatalog, toastError } = vi.hoisted(
  () => ({
    replace: vi.fn(),
    fetchSetupStatus: vi.fn(),
    fetchCatalog: vi.fn(),
    toastError: vi.fn(),
  }),
);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
}));
vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/c",
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/features/settings/api/providersApi", () => ({
  providersApi: { fetchSetupStatus, fetchCatalog },
}));
vi.mock("@/lib/toast", () => ({
  toast: { error: toastError, success: vi.fn() },
}));

import RedirectPage from "@/app/[locale]/(main)/redirect/page";
import {
  getSetupStatusServer,
  resolveInstanceAuthMode,
} from "@/features/auth/api/serverSetupStatusApi";
import LoginModal from "@/features/auth/components/LoginModal";
import { useProviderCatalog } from "@/features/settings/hooks/useProviderCatalog";
import {
  useDeployment,
  useSetupStatus,
} from "@/features/settings/hooks/useSetupStatus";
import { useLoginModalStore } from "@/stores/loginModalStore";

function withQueryClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubEnv("API_BASE_URL_INTERNAL", "http://gaia-backend:8000/api/v1/");
  fetchSetupStatus.mockRejectedValue(new Error("404 Not Found"));
  fetchCatalog.mockRejectedValue(new Error("404 Not Found"));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("signing in to hosted GAIA", () => {
  it("lands in the app without asking for setup status or toasting", async () => {
    render(<RedirectPage />, { wrapper: withQueryClient() });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    expect(fetchSetupStatus).not.toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
    expect(replace).toHaveBeenCalledWith("/c");
  });

  it("opens the login modal without probing the instance's auth mode", async () => {
    useLoginModalStore.setState({ open: true });
    render(<LoginModal />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });

    expect(fetchSetupStatus).not.toHaveBeenCalled();
  });
});

describe("the setup queries on hosted GAIA", () => {
  it("never fetch status or catalog, and report the hosted deployment", async () => {
    const wrapper = withQueryClient();
    const { result } = renderHook(
      () => ({
        status: useSetupStatus(),
        catalog: useProviderCatalog(),
        deployment: useDeployment(),
      }),
      { wrapper },
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });

    expect(fetchSetupStatus).not.toHaveBeenCalled();
    expect(fetchCatalog).not.toHaveBeenCalled();
    expect(result.current.deployment.kind).toBe("production");
  });
});

describe("a self-hosted instance before its status loads", () => {
  it("reports the self-host deployment, never GAIA Cloud's", () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
    fetchSetupStatus.mockReturnValue(new Promise(() => undefined));
    const { result } = renderHook(() => useDeployment(), {
      wrapper: withQueryClient(),
    });

    expect(result.current.kind).toBe("selfhost");
    expect(result.current.bills).toBe(false);
    expect(result.current.gaia_support).toBe(false);
  });
});

describe("hosted server-rendered auth pages", () => {
  it("resolve WorkOS without a request or an error log", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {
      // Asserted below; nothing must be logged.
    });

    expect(await resolveInstanceAuthMode()).toBe("workos");
    expect(await getSetupStatusServer()).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(consoleError).not.toHaveBeenCalled();
  });
});
