// @vitest-environment jsdom
/** GAIA's hosted release notes announce hosted features; a self-hosted instance shows none. */

import type { SetupStatusResponse } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchSetupStatus = vi.fn<() => Promise<SetupStatusResponse>>();

vi.mock("@/features/settings/api/providersApi", async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import("@/features/settings/api/providersApi")
    >();
  return {
    ...actual,
    providersApi: { fetchSetupStatus: () => fetchSetupStatus() },
  };
});

import { useReleases } from "@/features/whats-new/hooks/useReleases";

const RELEASE = {
  id: "r1",
  title: "Plans You Can Buy From Chat",
  date: "2026-10-01T00:00:00.000Z",
};

const SELFHOST_STATUS: SetupStatusResponse = {
  auth_mode: "local",
  billing_enabled: false,
  has_admin_account: true,
  registration_policy: "invite_only",
  needs_setup: false,
  plans_seeded: false,
  local_code_sandbox: false,
  blob_store: "local",
  gaia_support: false,
  providers: {},
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function stubReleaseFeed(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ releases: [RELEASE] }))),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  fetchSetupStatus.mockReset();
});

describe("useReleases", () => {
  it("serves no hosted announcements on a self-hosted instance", async () => {
    fetchSetupStatus.mockResolvedValue(SELFHOST_STATUS);
    stubReleaseFeed();

    const { result } = renderHook(() => useReleases(), { wrapper });

    await waitFor(() => expect(fetchSetupStatus).toHaveBeenCalled());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.releases).toEqual([]);
    expect(result.current.latest).toBeNull();
  });

  it("serves the release notes on hosted GAIA, which has no setup status", async () => {
    fetchSetupStatus.mockRejectedValue(new Error("404"));
    stubReleaseFeed();

    const { result } = renderHook(() => useReleases(), { wrapper });

    await waitFor(() => expect(result.current.releases).toHaveLength(1));
    expect(result.current.latest?.title).toBe(RELEASE.title);
  });
});
