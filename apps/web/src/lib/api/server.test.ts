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
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    fetchMock.mockReset();
  });

  it("refuses to read the API during the build", async () => {
    vi.stubEnv("NEXT_PHASE", PHASE_PRODUCTION_BUILD);

    await expect(serverFetch(new Request(CONFIG_URL))).rejects.toThrow(
      "ran during the build",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("gives a visitor's request one attempt, bounded by the request timeout", async () => {
    fetchMock.mockRejectedValue(timeout());
    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");

    await expect(serverFetch(new Request(CONFIG_URL))).rejects.toThrow(
      "timeout",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(timeoutSpy.mock.calls).toEqual([[10_000]]);
  });

  it("caches a read in the data cache only when it names a revalidate window", async () => {
    fetchMock.mockResolvedValue(new Response("{}"));

    await serverFetch(new Request(CONFIG_URL));
    await serverFetch(new Request(CONFIG_URL), { revalidate: 3600 });

    expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("next");
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      next: { revalidate: 3600 },
    });
  });
});
