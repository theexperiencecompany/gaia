import { describe, expect, it } from "vitest";
import {
  LLM_PROVIDERS,
  saveProviderArgs,
  validateLlmFlags,
} from "../../src/lib/llm-flags.js";

describe("LLM_PROVIDERS", () => {
  it("offers every chat provider the API serves", () => {
    expect([...LLM_PROVIDERS]).toEqual([
      "openrouter",
      "gemini",
      "openai",
      "ollama",
      "custom",
    ]);
  });
});

describe("validateLlmFlags", () => {
  it.each(["openrouter", "gemini", "openai"] as const)(
    "accepts %s with a key",
    (llmProvider) => {
      expect(() =>
        validateLlmFlags({ llmProvider, llmKey: "sk" }),
      ).not.toThrow();
    },
  );

  it("refuses a keyed provider without --llm-key", () => {
    expect(() => validateLlmFlags({ llmProvider: "gemini" })).toThrow(
      "--llm-provider gemini requires --llm-key.",
    );
  });

  it("refuses an endpoint or model on a provider whose card has none", () => {
    expect(() =>
      validateLlmFlags({
        llmProvider: "openrouter",
        llmKey: "sk",
        llmBaseUrl: "https://x",
      }),
    ).toThrow("--llm-base-url is not used with --llm-provider openrouter.");
    expect(() =>
      validateLlmFlags({ llmProvider: "openai", llmKey: "sk", llmModel: "m" }),
    ).toThrow("--llm-model is not used with --llm-provider openai.");
  });

  it("accepts keyless Ollama with or without an endpoint and model", () => {
    expect(() => validateLlmFlags({ llmProvider: "ollama" })).not.toThrow();
    expect(() =>
      validateLlmFlags({
        llmProvider: "ollama",
        llmBaseUrl: "http://lan:11434",
        llmModel: "qwen3",
      }),
    ).not.toThrow();
  });

  it("refuses a key on Ollama", () => {
    expect(() =>
      validateLlmFlags({ llmProvider: "ollama", llmKey: "sk" }),
    ).toThrow("--llm-key is not used with --llm-provider ollama.");
  });

  it("requires every field the custom endpoint needs", () => {
    expect(() =>
      validateLlmFlags({ llmProvider: "custom", llmKey: "sk", llmModel: "m" }),
    ).toThrow("--llm-provider custom requires --llm-base-url.");
    expect(() =>
      validateLlmFlags({
        llmProvider: "custom",
        llmKey: "sk",
        llmBaseUrl: "https://gw/v1",
      }),
    ).toThrow("--llm-provider custom requires --llm-model.");
    expect(() =>
      validateLlmFlags({
        llmProvider: "custom",
        llmKey: "sk",
        llmBaseUrl: "https://gw/v1",
        llmModel: "m",
      }),
    ).not.toThrow();
  });

  it("refuses a provider field without --llm-provider, naming every choice", () => {
    expect(() => validateLlmFlags({ llmKey: "sk" })).toThrow(
      "--llm-key requires --llm-provider <openrouter|gemini|openai|ollama|custom>.",
    );
    expect(() => validateLlmFlags({ llmModel: "m" })).toThrow(
      /^--llm-model requires --llm-provider/,
    );
  });

  it("refuses --no-start, since the provider is saved into the running instance", () => {
    expect(() =>
      validateLlmFlags({ llmProvider: "ollama", noStart: true }),
    ).toThrow(/cannot be combined with --no-start/);
  });

  it("accepts no provider flags at all", () => {
    expect(() => validateLlmFlags({ noStart: true })).not.toThrow();
  });
});

describe("saveProviderArgs", () => {
  it("passes the endpoint and model and never the key", () => {
    const args = saveProviderArgs({
      llmProvider: "custom",
      llmKey: "sk-secret",
      llmBaseUrl: "https://gw/v1",
      llmModel: "m",
    });

    expect(args).toEqual([
      "--provider",
      "custom",
      "--base-url",
      "https://gw/v1",
      "--model",
      "m",
    ]);
    expect(args.join(" ")).not.toContain("sk-secret");
  });

  it("omits fields that were not given", () => {
    expect(saveProviderArgs({ llmProvider: "ollama" })).toEqual([
      "--provider",
      "ollama",
    ]);
  });
});
