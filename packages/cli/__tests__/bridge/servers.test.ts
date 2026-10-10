import { describe, expect, it, vi } from "vitest";

import {
  assertLoopbackUrl,
  guardedFetch,
} from "../../src/commands/bridge/servers.js";

// A url server must point at THIS machine — otherwise the cloud could drive the
// daemon into the user's LAN (SSRF pivot). Config is user-editable, so this guard
// runs on save and on open.
describe("assertLoopbackUrl", () => {
  it.each([
    "http://localhost:9000/mcp",
    "http://127.0.0.1:8080/mcp",
    "https://localhost/mcp",
    "http://[::1]:3000/mcp",
  ])("accepts loopback %s", (url) => {
    expect(() => assertLoopbackUrl(url)).not.toThrow();
  });

  it.each([
    "http://192.168.1.5/mcp",
    "https://example.com/mcp",
    "http://10.0.0.1:9000/mcp",
    "http://169.254.169.254/mcp",
  ])("rejects non-loopback %s", (url) => {
    expect(() => assertLoopbackUrl(url)).toThrow(/this machine/);
  });

  it("rejects a non-http(s) scheme", () => {
    expect(() => assertLoopbackUrl("ftp://localhost/mcp")).toThrow(/http/);
  });
});

// The MCP SDK follows redirects by default and its requestInit.redirect never
// reaches the initial GET — so credential-bearing requests go through
// guardedFetch, which refuses to carry headers across origins.
describe("guardedFetch", () => {
  const ok = (body = "{}") =>
    new Response(body, {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  const redirect = (location: string | null) =>
    new Response(null, {
      status: 307,
      ...(location ? { headers: { location } } : {}),
    });

  it("passes non-redirect responses through untouched", async () => {
    const seen: RequestInit[] = [];
    vi.stubGlobal("fetch", async (_input: unknown, init?: RequestInit) => {
      seen.push(init ?? {});
      return ok();
    });
    try {
      const res = await guardedFetch("http://localhost:3000/mcp", {
        headers: { "x-api-key": "secret" },
      });
      expect(res.status).toBe(200);
      expect(await res.json()).toEqual({});
      expect(seen[0]?.headers).toEqual({ "x-api-key": "secret" });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("refuses a cross-origin redirect instead of forwarding headers", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", async (input: unknown) => {
      calls.push(String(input));
      return redirect("https://evil.example/collect");
    });
    try {
      await expect(
        guardedFetch("http://localhost:3000/mcp", {
          headers: { "x-api-key": "secret" },
        }),
      ).rejects.toThrow(/refusing 307 redirect to https:\/\/evil\.example/);
      // The evil host was never requested — headers never left the machine.
      expect(calls).toEqual(["http://localhost:3000/mcp"]);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("follows a same-origin redirect (e.g. / -> /mcp)", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", async (input: unknown) => {
      calls.push(String(input));
      if (String(input) === "http://localhost:3000/") {
        return redirect("/mcp");
      }
      return ok();
    });
    try {
      const res = await guardedFetch("http://localhost:3000/", {
        headers: { "x-api-key": "secret" },
      });
      expect(res.status).toBe(200);
      expect(calls).toEqual([
        "http://localhost:3000/",
        "http://localhost:3000/mcp",
      ]);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("rejects a redirect with no location", async () => {
    vi.stubGlobal("fetch", async () => redirect(null));
    try {
      await expect(guardedFetch("http://localhost:3000/mcp")).rejects.toThrow(
        /refusing 307 redirect/,
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("gives up after too many same-origin hops", async () => {
    vi.stubGlobal("fetch", async (input: unknown) =>
      redirect(`${String(input)}/deeper`),
    );
    try {
      await expect(guardedFetch("http://localhost:3000/mcp")).rejects.toThrow(
        /too many redirects/,
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
