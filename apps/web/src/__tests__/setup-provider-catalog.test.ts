// @vitest-environment jsdom
/** Setup cards and LLM readiness derive from GET /setup/catalog, not web literals. */

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";

const testProvider = vi.fn();
const upsertProvider = vi.fn();

vi.mock("@/features/settings/api/providersApi", async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import("@/features/settings/api/providersApi")
    >();
  return {
    ...actual,
    providersApi: {
      testProvider: (...args: unknown[]) => testProvider(...args),
      upsertProvider: (...args: unknown[]) => upsertProvider(...args),
    },
  };
});

import { isAnyLlmConfigured } from "@/features/settings/hooks/useSetupStatus";
import { useProviderSetup } from "@/features/setup-wizard/hooks/useProviderSetup";
import {
  resolveLlmProviderCards,
  resolveProviderCard,
} from "@/features/setup-wizard/utils/providerCards";

const entry = (overrides: Partial<ProviderCatalog["providers"][string]>) => ({
  label: "",
  base_url: "",
  default_model: "",
  favicon_domain: "",
  needs_base_url: false,
  ...overrides,
});

const CATALOG: ProviderCatalog = {
  llm_provider_keys: ["openrouter", "gemini", "openai", "ollama", "custom"],
  providers: {
    openrouter: entry({ default_model: "router-chat-from-catalog" }),
    gemini: entry({ default_model: "gemini-from-catalog" }),
    openai: entry({ default_model: "openai-from-catalog" }),
    ollama: entry({
      base_url: "http://ollama.catalog:11434",
      default_model: "ollama-from-catalog",
      needs_base_url: true,
    }),
    custom: entry({ needs_base_url: true }),
    tavily: entry({}),
  },
  custom_presets: {
    opencode: entry({
      label: "OpenCode",
      base_url: "https://gateway.catalog/v1",
      default_model: "preset-model-from-catalog",
      favicon_domain: "opencode.ai",
    }),
  },
};

const statusWith = (configured: string[]): SetupStatus => ({
  auth_mode: "local",
  billing_enabled: false,
  has_admin_account: true,
  registration_policy: "invite_only",
  needs_setup: true,
  plans_seeded: true,
  local_code_sandbox: false,
  providers: Object.fromEntries(
    configured.map((key) => [
      key,
      { configured: true, source: "stored" as const },
    ]),
  ),
});

const llmCard = (key: string) => {
  const card = resolveLlmProviderCards(CATALOG).find((c) => c.key === key);
  if (!card) throw new Error(`no ${key} card`);
  return card;
};

describe("LLM provider cards", () => {
  it("follow the catalog's priority order, with OpenAI as a probed chat card", () => {
    expect(resolveLlmProviderCards(CATALOG).map((c) => c.key)).toEqual([
      "openrouter",
      "gemini",
      "openai",
      "ollama",
      "custom",
    ]);
    expect(llmCard("openai").connectionTestable).toBe(true);
  });

  it("take endpoint defaults and preset gateways from the catalog", () => {
    expect(llmCard("ollama")).toMatchObject({
      defaultBaseUrl: "http://ollama.catalog:11434",
      defaultModel: "ollama-from-catalog",
    });
    expect(llmCard("custom").presets).toEqual([
      expect.objectContaining({
        key: "opencode",
        base_url: "https://gateway.catalog/v1",
      }),
    ]);
  });

  it("fail loud when the catalog lists a chat provider the web has no copy for", () => {
    expect(() =>
      resolveLlmProviderCards({
        ...CATALOG,
        llm_provider_keys: ["mystery"],
      }),
    ).toThrow(/mystery/);
  });
});

describe("isAnyLlmConfigured", () => {
  it("counts an OpenAI-only instance as chat-ready", () => {
    expect(isAnyLlmConfigured(statusWith(["openai"]), CATALOG)).toBe(true);
  });

  it("does not count a tool key toward chat readiness", () => {
    expect(isAnyLlmConfigured(statusWith(["tavily"]), CATALOG)).toBe(false);
  });
});

describe("useProviderSetup", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    testProvider.mockResolvedValue({ ok: true, detail: "ok", models: [] });
    upsertProvider.mockResolvedValue(undefined);
  });

  it("never stores the catalog default model implicitly", async () => {
    const { result } = renderHook(() =>
      useProviderSetup(llmCard("openrouter"), vi.fn()),
    );
    act(() => result.current.setApiKey("sk-test"));
    await act(() => result.current.connect());

    expect(upsertProvider).toHaveBeenCalledWith("openrouter", {
      api_key: "sk-test",
    });
  });

  it("applies a catalog preset's endpoint and model", async () => {
    const custom = llmCard("custom");
    const { result } = renderHook(() => useProviderSetup(custom, vi.fn()));
    act(() => {
      result.current.setApiKey("sk-test");
      result.current.applyPreset(custom.presets[0]);
    });
    await act(() => result.current.connect());

    expect(upsertProvider).toHaveBeenCalledWith("custom", {
      api_key: "sk-test",
      base_url: "https://gateway.catalog/v1",
      model: "preset-model-from-catalog",
      preset: "opencode",
    });
  });

  it("prefills a non-LLM card with no endpoint defaults", () => {
    const tavily = resolveProviderCard(
      {
        key: "tavily",
        label: "Tavily",
        description: "",
        faviconDomain: "tavily.com",
        showApiKey: true,
        showBaseUrl: false,
        showModel: false,
        connectionTestable: false,
        hasPresets: false,
      },
      CATALOG,
    );
    expect(tavily).toMatchObject({
      defaultBaseUrl: "",
      defaultModel: "",
      presets: [],
    });
  });
});
