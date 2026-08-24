import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  READINESS_INTERVAL_MS,
  READINESS_TIMEOUT_MS,
  waitForServices,
  waitForUpReadiness,
} from "../../../src/commands/up/readiness.js";
import { createStore } from "../../../src/ui/store.js";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** Stub global fetch and return the mock so tests can assert call URLs. */
function stubFetch(
  impl: (url: string) => Promise<{ ok: boolean; status: number }>,
) {
  const mock = vi.fn(impl);
  vi.stubGlobal("fetch", mock);
  return mock;
}

function calledUrls(mock: ReturnType<typeof stubFetch>): string[] {
  return mock.mock.calls.map(([url]) => String(url));
}

const TARGETS = [
  {
    label: "API",
    url: "http://localhost:8000/health",
    requireOk: true,
  },
  {
    label: "Web",
    url: "http://localhost:3000/login",
    requireOk: false,
  },
] as const;

describe("waitForServices", () => {
  it("uses a 5s poll interval within a 5 minute budget", () => {
    expect(READINESS_INTERVAL_MS).toBe(5_000);
    expect(READINESS_TIMEOUT_MS).toBe(5 * 60_000);
  });

  it("resolves ready once every target answers, probing both URLs", async () => {
    const mock = stubFetch(async () => ({ ok: true, status: 200 }));

    const result = await waitForServices([...TARGETS], {
      timeoutMs: 60_000,
    });

    expect(result).toEqual({ ready: true });
    const urls = calledUrls(mock);
    expect(urls).toContain("http://localhost:8000/health");
    expect(urls).toContain("http://localhost:3000/login");
  });

  it("keeps polling until a connection-refused target starts answering", async () => {
    let apiCalls = 0;
    const mock = stubFetch(async (url) => {
      if (url.endsWith("/health")) {
        apiCalls += 1;
        if (apiCalls < 3) throw new Error("ECONNREFUSED");
      }
      return { ok: true, status: 200 };
    });

    const promise = waitForServices([...TARGETS], {
      timeoutMs: 60_000,
      intervalMs: READINESS_INTERVAL_MS,
    });
    // Round 1 runs immediately; two failed rounds sit behind 5s sleeps.
    await vi.advanceTimersByTimeAsync(15_000);

    expect(await promise).toEqual({ ready: true });
    expect(calledUrls(mock).filter((u) => u.endsWith("/health"))).toHaveLength(
      3,
    );
  });

  it("requires 2xx only for requireOk targets — any response readies the web page", async () => {
    stubFetch(async (url) =>
      url.endsWith("/login")
        ? { ok: false, status: 302 }
        : { ok: true, status: 200 },
    );

    const result = await waitForServices([...TARGETS], { timeoutMs: 60_000 });

    expect(result).toEqual({ ready: true });
  });

  it("keeps waiting while a requireOk target answers with an error status", async () => {
    stubFetch(async (url) => {
      if (url.endsWith("/health")) return { ok: false, status: 503 };
      throw new Error("ECONNREFUSED");
    });

    const seen: string[][] = [];
    const promise = waitForServices([...TARGETS], {
      timeoutMs: 10_000,
      intervalMs: READINESS_INTERVAL_MS,
      onProgress: (pendingLabels) => seen.push([...pendingLabels]),
    });
    await vi.advanceTimersByTimeAsync(20_000);

    expect(await promise).toEqual({
      ready: false,
      stillStarting: "API, Web",
    });
    expect(seen).toEqual([
      ["API", "Web"],
      ["API", "Web"],
    ]);
  });

  it("names only the services still starting when the budget runs out", async () => {
    stubFetch(async (url) => {
      if (url.endsWith("/health")) return { ok: true, status: 200 };
      throw new Error("ECONNREFUSED");
    });

    const promise = waitForServices([...TARGETS], {
      timeoutMs: 10_000,
      intervalMs: READINESS_INTERVAL_MS,
    });
    await vi.advanceTimersByTimeAsync(20_000);

    expect(await promise).toEqual({ ready: false, stillStarting: "Web" });
  });

  it("reports progress with the labels that have not answered yet", async () => {
    let webCalls = 0;
    stubFetch(async (url) => {
      if (url.endsWith("/login")) {
        webCalls += 1;
        if (webCalls < 3) throw new Error("ECONNREFUSED");
      }
      return { ok: true, status: 200 };
    });

    const seen: string[][] = [];
    const promise = waitForServices([...TARGETS], {
      timeoutMs: 60_000,
      intervalMs: READINESS_INTERVAL_MS,
      onProgress: (pendingLabels) => seen.push([...pendingLabels]),
    });
    await vi.advanceTimersByTimeAsync(15_000);

    expect(await promise).toEqual({ ready: true });
    // API answers in round 1 and drops out; only Web appears in progress.
    expect(seen).toEqual([["Web"], ["Web"]]);
  });
});

describe("waitForUpReadiness", () => {
  it("drives the dependency spinner phase and completes on readiness", async () => {
    stubFetch(async () => ({ ok: true, status: 200 }));
    const store = createStore();

    const result = await waitForUpReadiness(store, {
      apiPort: 8000,
      webPort: 3000,
    });

    expect(result).toEqual({ ready: true });
    expect(store.currentState.data.dependencyComplete).toBe(true);
    expect(store.currentState.data.dependencyPhase).toBe(
      "All services are ready!",
    );
  });

  it("finishes honestly naming what is still starting on timeout", async () => {
    stubFetch(async () => {
      throw new Error("ECONNREFUSED");
    });
    const store = createStore();

    const promise = waitForUpReadiness(store, {
      apiPort: 8000,
      webPort: 3000,
    });
    await vi.advanceTimersByTimeAsync(READINESS_TIMEOUT_MS + 60_000);

    expect(await promise).toEqual({
      ready: false,
      stillStarting: "API, Web",
    });
    expect(store.currentState.data.dependencyComplete).toBe(true);
    expect(store.currentState.data.dependencyPhase).toBe(
      "Still starting: API, Web",
    );
  });

  it("shows which services are being waited on while polling", async () => {
    stubFetch(async () => {
      throw new Error("ECONNREFUSED");
    });
    const store = createStore();

    const promise = waitForUpReadiness(store, {
      apiPort: 8000,
      webPort: 3000,
    });
    await vi.advanceTimersByTimeAsync(READINESS_INTERVAL_MS * 2);

    expect(store.currentState.data.dependencyComplete).toBe(false);
    expect(store.currentState.data.dependencyPhase).toBe(
      "Waiting for API and Web to come online...",
    );

    // Exhaust the budget so no poll loop dangles past the test.
    await vi.advanceTimersByTimeAsync(READINESS_TIMEOUT_MS);
    expect(await promise).toEqual({ ready: false, stillStarting: "API, Web" });
  });
});
