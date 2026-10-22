// @vitest-environment jsdom
/** Wizard, Settings and the Ollama one-click connect a provider by one rule: probe first, store only what answered. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { testProvider, upsertProvider, deleteProvider } = vi.hoisted(() => ({
  testProvider: vi.fn(),
  upsertProvider: vi.fn(async () => undefined),
  deleteProvider: vi.fn(async () => undefined),
}));

vi.mock("@/features/settings/api/providersApi", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/settings/api/providersApi")
  >()),
  providersApi: { testProvider, upsertProvider, deleteProvider },
}));
vi.mock("@/hooks/useConfirmation", () => ({
  useConfirmation: () => ({ confirm: vi.fn(), confirmationProps: {} }),
}));
vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { setupKeys } from "@/features/settings/api/queryKeys";
import { useConfigureProvider } from "@/features/settings/hooks/useConfigureProvider";
import { useProviderConnect } from "@/features/settings/hooks/useProviderConnect";
import type { CatalogProvider } from "@/features/settings/utils/providerCatalog";

afterEach(() => vi.clearAllMocks());

function withQueryClient(client = new QueryClient()) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

/** A client with every credential-dependent read cached, to see which ones a write invalidates. */
function seededClient(): QueryClient {
  const client = new QueryClient();
  for (const key of [
    setupKeys.status,
    setupKeys.providers,
    setupKeys.composio,
    setupKeys.catalog,
  ]) {
    client.setQueryData(key, {});
  }
  return client;
}

const isStale = (client: QueryClient, key: readonly unknown[]) =>
  client.getQueryState(key)?.isInvalidated === true;

describe("useProviderConnect", () => {
  it("stores nothing when the probe fails", async () => {
    testProvider.mockResolvedValue({ ok: false, detail: "401", models: [] });
    const client = seededClient();
    const { result } = renderHook(
      () => useProviderConnect("openai", { connectionTestable: true }),
      { wrapper: withQueryClient(client) },
    );

    let stored: boolean | undefined;
    await act(async () => {
      stored = await result.current.connect({ api_key: "bad" });
    });

    expect(stored).toBe(false);
    expect(upsertProvider).not.toHaveBeenCalled();
    expect(isStale(client, setupKeys.status)).toBe(false);
    expect(result.current.outcome?.ok).toBe(false);
  });

  it("stores what the probe accepted and refreshes what the credential changes", async () => {
    testProvider.mockResolvedValue({ ok: true, detail: "ok", models: ["m"] });
    const client = seededClient();
    const { result } = renderHook(
      () => useProviderConnect("openai", { connectionTestable: true }),
      { wrapper: withQueryClient(client) },
    );

    let stored: boolean | undefined;
    await act(async () => {
      stored = await result.current.connect({ api_key: "good" });
    });

    expect(stored).toBe(true);
    expect(upsertProvider).toHaveBeenCalledWith("openai", { api_key: "good" });
    expect(isStale(client, setupKeys.status)).toBe(true);
    expect(isStale(client, setupKeys.providers)).toBe(true);
    expect(isStale(client, setupKeys.composio)).toBe(true);
    expect(isStale(client, setupKeys.catalog)).toBe(false);
  });

  it("refreshes the same reads after removing a credential", async () => {
    const client = seededClient();
    const { result } = renderHook(
      () => useProviderConnect("openai", { connectionTestable: true }),
      { wrapper: withQueryClient(client) },
    );

    await act(() => result.current.disconnect());

    expect(deleteProvider).toHaveBeenCalledWith("openai");
    expect(isStale(client, setupKeys.status)).toBe(true);
    expect(isStale(client, setupKeys.providers)).toBe(true);
  });

  it("saves a provider the backend cannot probe without testing it", async () => {
    const { result } = renderHook(
      () => useProviderConnect("tavily", { connectionTestable: false }),
      { wrapper: withQueryClient() },
    );

    await act(() => result.current.connect({ api_key: "k" }));

    expect(testProvider).not.toHaveBeenCalled();
    expect(upsertProvider).toHaveBeenCalledOnce();
  });
});

describe("Settings' configure dialog", () => {
  it("probes before it stores, like the wizard", async () => {
    testProvider.mockResolvedValue({ ok: false, detail: "401", models: [] });
    const row = {
      key: "openai",
      label: "OpenAI",
      base_url: null,
      key_url: null,
      connectionTestable: true,
      takes_model: false,
    } as unknown as CatalogProvider;
    const { result } = renderHook(
      () => useConfigureProvider({ row, presets: [] }),
      { wrapper: withQueryClient() },
    );

    act(() => result.current.setApiKey("bad"));
    await act(() => result.current.save());

    expect(testProvider).toHaveBeenCalledOnce();
    expect(upsertProvider).not.toHaveBeenCalled();
  });
});
