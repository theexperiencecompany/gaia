/** A self-host auth page whose instance status cannot be read fails loud, never falls back to WorkOS. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/server", () => ({ connection: vi.fn(async () => undefined) }));

import {
  getSetupStatusServer,
  resolveInstanceAuthMode,
} from "@/features/auth/api/serverSetupStatusApi";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
  vi.stubEnv("API_BASE_URL_INTERNAL", "http://gaia-backend:8000/api/v1/");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("reading the instance status on the server", () => {
  it("rejects when the API answers with an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("down", { status: 503 })),
    );

    await expect(resolveInstanceAuthMode()).rejects.toThrow(/503/);
    await expect(getSetupStatusServer()).rejects.toThrow(/503/);
  });

  it("rejects when the API is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );

    await expect(resolveInstanceAuthMode()).rejects.toThrow(/fetch failed/);
  });

  it("rejects when no server-side API base is configured", async () => {
    vi.stubEnv("API_BASE_URL_INTERNAL", "");
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "/api/v1/");

    await expect(resolveInstanceAuthMode()).rejects.toThrow(/API base URL/);
  });

  it("reads the auth mode the instance reports", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ auth_mode: "local" })),
    );

    await expect(resolveInstanceAuthMode()).resolves.toBe("local");
  });
});
