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
