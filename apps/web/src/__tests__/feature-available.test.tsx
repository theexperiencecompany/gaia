// @vitest-environment jsdom
/** Whether a deployment can run a feature: always on GAIA Cloud with no request, from setup status on self-host. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { fetchSetupStatus } = vi.hoisted(() => ({
  fetchSetupStatus: vi.fn(),
}));

vi.mock("@/features/settings/api/providersApi", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/settings/api/providersApi")
  >()),
  providersApi: { fetchSetupStatus },
}));

import { useFeatureAvailable } from "@/features/settings/hooks/useSetupStatus";

function renderVoiceAvailable() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useFeatureAvailable("voice"), { wrapper });
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("useFeatureAvailable", () => {
  it("is true on GAIA Cloud without fetching setup status", () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "");
    const { result } = renderVoiceAvailable();

    expect(result.current).toBe(true);
    expect(fetchSetupStatus).not.toHaveBeenCalled();
  });

  it("follows setup status on a self-hosted instance", async () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
    fetchSetupStatus.mockResolvedValue({
      features: { voice: { working: false, available: false, in_use: [] } },
    });
    const { result } = renderVoiceAvailable();

    await waitFor(() => expect(fetchSetupStatus).toHaveBeenCalled());
    expect(result.current).toBe(false);
  });

  it("is true on a self-hosted instance that can run the feature", async () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
    fetchSetupStatus.mockResolvedValue({
      features: { voice: { working: true, available: true, in_use: [] } },
    });
    const { result } = renderVoiceAvailable();

    await waitFor(() => expect(result.current).toBe(true));
  });
});
