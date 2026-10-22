// @vitest-environment jsdom
/** Wizard, Settings and the Ollama one-click connect a provider by one rule: probe first, store only what answered. */

import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { testProvider, upsertProvider } = vi.hoisted(() => ({
  testProvider: vi.fn(),
  upsertProvider: vi.fn(async () => undefined),
}));

vi.mock("@/features/settings/api/providersApi", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/settings/api/providersApi")
  >()),
  providersApi: { testProvider, upsertProvider },
}));
vi.mock("@/hooks/useConfirmation", () => ({
  useConfirmation: () => ({ confirm: vi.fn(), confirmationProps: {} }),
}));
vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { useConfigureProvider } from "@/features/settings/hooks/useConfigureProvider";
import { useProviderConnect } from "@/features/settings/hooks/useProviderConnect";
import type { CatalogProvider } from "@/features/settings/utils/providerCatalog";

afterEach(() => vi.clearAllMocks());

describe("useProviderConnect", () => {
  it("stores nothing when the probe fails", async () => {
    testProvider.mockResolvedValue({ ok: false, detail: "401", models: [] });
    const onSaved = vi.fn();
    const { result } = renderHook(() =>
      useProviderConnect("openai", { connectionTestable: true, onSaved }),
    );

    await act(() => result.current.connect({ api_key: "bad" }));

    expect(upsertProvider).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(result.current.outcome?.ok).toBe(false);
  });

  it("stores what the probe accepted", async () => {
    testProvider.mockResolvedValue({ ok: true, detail: "ok", models: ["m"] });
    const onSaved = vi.fn();
    const { result } = renderHook(() =>
      useProviderConnect("openai", { connectionTestable: true, onSaved }),
    );

    await act(() => result.current.connect({ api_key: "good" }));

    expect(upsertProvider).toHaveBeenCalledWith("openai", { api_key: "good" });
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("saves a provider the backend cannot probe without testing it", async () => {
    const { result } = renderHook(() =>
      useProviderConnect("tavily", {
        connectionTestable: false,
        onSaved: vi.fn(),
      }),
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
    const { result } = renderHook(() =>
      useConfigureProvider({ row, presets: [], onSaved: vi.fn() }),
    );

    act(() => result.current.setApiKey("bad"));
    await act(() => result.current.save());

    expect(testProvider).toHaveBeenCalledOnce();
    expect(upsertProvider).not.toHaveBeenCalled();
  });
});
