// @vitest-environment node
import { PHASE_PRODUCTION_BUILD } from "next/constants";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { serverFetch } from "@/lib/api/server";

const CONFIG_URL = "https://api.example.test/api/v1/integrations/config";

function timeout(): DOMException {
  return new DOMException(
    "The operation was aborted due to timeout",
    "TimeoutError",
  );
}

function rateLimited(retryAfter: string): Response {
  return new Response('{"message":"120 per 1 minute"}', {
    status: 429,
    headers: { "Retry-After": retryAfter },
  });
}

describe("serverFetch", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    fetchMock.mockReset();
  });

  it("carries the server's INTERNAL_API_TOKEN on every attempt", async () => {
    vi.stubEnv("INTERNAL_API_TOKEN", "t0ken");
    vi.stubEnv("NEXT_PHASE", PHASE_PRODUCTION_BUILD);
    fetchMock
      .mockRejectedValueOnce(timeout())
      .mockResolvedValueOnce(new Response("{}", { status: 200 }));

    const pending = serverFetch(new Request(CONFIG_URL));
    await vi.runAllTimersAsync();
    await pending;

    const sent = fetchMock.mock.calls.map(([input]) =>
      (input as Request).headers.get("X-Gaia-Internal"),
    );
    expect(sent).toEqual(["t0ken", "t0ken"]);
  });

  it("retries a build-time timeout and returns the response that arrives", async () => {
    vi.stubEnv("NEXT_PHASE", PHASE_PRODUCTION_BUILD);
    fetchMock
      .mockRejectedValueOnce(timeout())
      .mockRejectedValueOnce(timeout())
      .mockResolvedValueOnce(new Response("{}", { status: 200 }));

    const pending = serverFetch(new Request(CONFIG_URL));
    await vi.runAllTimersAsync();

    expect((await pending).status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("fails the build when the API stays down past every retry", async () => {
    vi.stubEnv("NEXT_PHASE", PHASE_PRODUCTION_BUILD);
    fetchMock.mockRejectedValue(timeout());

    const pending = serverFetch(new Request(CONFIG_URL));
    const outcome = expect(pending).rejects.toThrow("timeout");
    await vi.runAllTimersAsync();

    await outcome;
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("waits out a build-time 429 for its Retry-After, then returns the answer", async () => {
    vi.stubEnv("NEXT_PHASE", PHASE_PRODUCTION_BUILD);
    fetchMock
      .mockResolvedValueOnce(rateLimited("7"))
      .mockResolvedValueOnce(new Response("{}", { status: 200 }));

    const pending = serverFetch(new Request(CONFIG_URL));
    await vi.advanceTimersByTimeAsync(6_999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);

    expect((await pending).status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("hands the build the 429 once the refusals outlast the bound", async () => {
    vi.stubEnv("NEXT_PHASE", PHASE_PRODUCTION_BUILD);
    fetchMock.mockImplementation(async () => rateLimited("1"));

    const pending = serverFetch(new Request(CONFIG_URL));
    await vi.runAllTimersAsync();

    expect((await pending).status).toBe(429);
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });

  it("does not wait out a build-time 429 whose Retry-After is past the window", async () => {
    vi.stubEnv("NEXT_PHASE", PHASE_PRODUCTION_BUILD);
    fetchMock.mockResolvedValue(rateLimited("3600"));

    expect((await serverFetch(new Request(CONFIG_URL))).status).toBe(429);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("hands back a build-time 429 that names no Retry-After", async () => {
    vi.stubEnv("NEXT_PHASE", PHASE_PRODUCTION_BUILD);
    fetchMock.mockResolvedValue(new Response("{}", { status: 429 }));

    expect((await serverFetch(new Request(CONFIG_URL))).status).toBe(429);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("returns a visitor's 429 at once", async () => {
    fetchMock.mockResolvedValue(rateLimited("7"));

    expect((await serverFetch(new Request(CONFIG_URL))).status).toBe(429);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("gives a visitor's request one attempt", async () => {
    fetchMock.mockRejectedValue(timeout());

    await expect(serverFetch(new Request(CONFIG_URL))).rejects.toThrow(
      "timeout",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("bounds each attempt with a longer timeout at build time than at request time", async () => {
    fetchMock.mockResolvedValue(new Response("{}"));
    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");

    await serverFetch(new Request(CONFIG_URL));
    vi.stubEnv("NEXT_PHASE", PHASE_PRODUCTION_BUILD);
    await serverFetch(new Request(CONFIG_URL));

    expect(timeoutSpy.mock.calls).toEqual([[10_000], [30_000]]);
  });
});
