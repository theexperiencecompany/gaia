import {
  fetchBytesCapped,
  MediaReadTimeoutError,
  readResponseBytesCapped,
} from "@gaia/shared";
import { afterEach, describe, expect, it, vi } from "vitest";

const CHUNK = 256;

function endlessBody(): {
  body: ReadableStream<Uint8Array>;
  produced: () => number;
  cancelled: () => boolean;
} {
  let produced = 0;
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      produced += CHUNK;
      controller.enqueue(new Uint8Array(CHUNK).fill(9));
    },
    cancel() {
      cancelled = true;
    },
  });
  return { body, produced: () => produced, cancelled: () => cancelled };
}

function okResponse(body: ReadableStream<Uint8Array> | null): Response {
  return { ok: true, status: 200, body } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("readResponseBytesCapped", () => {
  it("stops at the cap and cancels a body that has more to give", async () => {
    const { body, produced, cancelled } = endlessBody();

    const bytes = await readResponseBytesCapped(okResponse(body), 1000, "Test");

    expect(bytes.byteLength).toBe(1000);
    expect(cancelled()).toBe(true);
    expect(produced()).toBeLessThanOrEqual(1000 + 2 * CHUNK);
  });

  it("returns every byte of a body that fits under the cap", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array([1, 2, 3]));
        controller.close();
      },
    });

    const bytes = await readResponseBytesCapped(okResponse(body), 64, "Test");

    expect(Array.from(bytes)).toEqual([1, 2, 3]);
  });

  it("throws with the HTTP status attached when the response is not ok", async () => {
    const response = {
      ok: false,
      status: 404,
      body: new ReadableStream<Uint8Array>(),
    } as unknown as Response;

    await expect(
      readResponseBytesCapped(response, 1000, "Test media"),
    ).rejects.toMatchObject({
      message: "Test media download failed (404)",
      status: 404,
    });
  });

  it("raises MediaReadTimeoutError when the body stalls past the deadline", async () => {
    const stalled = {
      ok: true,
      status: 200,
      body: new ReadableStream<Uint8Array>({
        pull() {
          return new Promise<void>(() => undefined);
        },
      }),
    } as unknown as Response;

    await expect(
      readResponseBytesCapped(stalled, 1000, "Test media", 20),
    ).rejects.toBeInstanceOf(MediaReadTimeoutError);
  });

  it("does not raise a timeout when the body finishes inside the deadline", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array([1, 2]));
        controller.close();
      },
    });

    const bytes = await readResponseBytesCapped(
      okResponse(body),
      1000,
      "Test media",
      5_000,
    );

    expect(Array.from(bytes)).toEqual([1, 2]);
  });

  it("throws when the response carries no body to read", async () => {
    await expect(
      readResponseBytesCapped(okResponse(null), 1000, "Test media"),
    ).rejects.toThrow("Test media download returned no body");
  });
});

describe("fetchBytesCapped", () => {
  it("caps the fetched body instead of buffering the whole payload", async () => {
    const { body, produced, cancelled } = endlessBody();
    const fetchMock = vi.fn(async () => okResponse(body));
    vi.stubGlobal("fetch", fetchMock);

    const bytes = await fetchBytesCapped(
      "https://cdn.test/file.bin",
      1000,
      "Test",
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(bytes.byteLength).toBe(1000);
    expect(cancelled()).toBe(true);
    expect(produced()).toBeLessThanOrEqual(1000 + 2 * CHUNK);
  });

  it("passes an abort signal only when a timeout is requested", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
      okResponse(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.close();
          },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchBytesCapped("https://cdn.test/a.bin", 16, "Test");
    await fetchBytesCapped("https://cdn.test/b.bin", 16, "Test", 5_000);

    expect(fetchMock.mock.calls[0][1]?.signal).toBeUndefined();
    expect(fetchMock.mock.calls[1][1]?.signal).toBeInstanceOf(AbortSignal);
  });

  it("surfaces a failed download as an error carrying the status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 403,
        body: null,
      })),
    );

    await expect(
      fetchBytesCapped("https://cdn.test/denied.bin", 16, "Test attachment"),
    ).rejects.toMatchObject({ status: 403 });
  });
});
