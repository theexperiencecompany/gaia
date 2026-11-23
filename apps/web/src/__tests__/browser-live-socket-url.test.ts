import { describe, expect, it, vi } from "vitest";

// The deployed proxies forward only the API base (with upgrades); a socket at
// the bare origin answered every live view with a 404 (GAIA-715).
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  apiBaseUrl: "https://api.example.com/api/v1",
  apiOrigin: "https://api.example.com",
}));

import { liveSocketUrl } from "@/features/browser/api/browserApi";
import type * as ApiClient from "@/lib/api/client";

describe("liveSocketUrl", () => {
  it("dials the live view under the API base, where the proxies upgrade", () => {
    expect(liveSocketUrl("Xk3p9qR2mN4t", null)).toBe(
      "wss://api.example.com/api/v1/browser/live/Xk3p9qR2mN4t",
    );
  });

  it("carries a takeover token for a session id", () => {
    expect(liveSocketUrl("sess 1", "t/k")).toBe(
      "wss://api.example.com/api/v1/browser/live/sess%201?t=t%2Fk",
    );
  });
});
