/**
 * Tests for connecting the desktop app to a self-hosted GAIA server: turning a
 * pasted address into the one origin the window may load, and probing that the
 * origin really is a GAIA server the desktop can sign in to. The probe runs
 * against a real local HTTP server, so redirects, status codes and bodies go
 * through the same fetch the main process uses.
 */

import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterEach, describe, expect, it } from "vitest";
import {
  normalizeServerAddress,
  probeSelfHostServer,
} from "../src/main/server-address";

describe("normalizeServerAddress", () => {
  it("defaults a bare hostname to https", () => {
    expect(normalizeServerAddress("gaia.example.com")).toEqual({
      ok: true,
      origin: "https://gaia.example.com",
    });
  });

  it("keeps an explicit http scheme and port", () => {
    expect(normalizeServerAddress(" http://192.168.1.20:8080 ")).toEqual({
      ok: true,
      origin: "http://192.168.1.20:8080",
    });
  });

  it("reduces an address copied from the browser to its origin", () => {
    expect(
      normalizeServerAddress("https://gaia.example.com/c/123?x=1#top"),
    ).toEqual({ ok: true, origin: "https://gaia.example.com" });
  });

  it.each([
    [""],
    ["   "],
    ["ftp://gaia.example.com"],
    ["javascript:alert(1)"],
    ["https://user:pass@gaia.example.com"],
    ["https://"],
  ])("rejects %j", (input) => {
    expect(normalizeServerAddress(input).ok).toBe(false);
  });
});

type Handler = Parameters<typeof createServer>[1];

/** Electron's net.fetch answers with an empty Response.url; mirror that so the
 * probe cannot lean on a field the main process never fills. */
async function netLikeFetch(url: string, init: RequestInit): Promise<Response> {
  const res = await fetch(url, init);
  return new Response(res.body, { status: res.status, headers: res.headers });
}

let server: Server | null = null;

async function serve(handler: Handler): Promise<string> {
  server = createServer(handler);
  await new Promise<void>((resolve) => server?.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return `http://127.0.0.1:${port}`;
}

function json(body: unknown, status = 200): Handler {
  return (_req, res) => {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  };
}

afterEach(async () => {
  await new Promise<void>((resolve) => {
    if (!server) return resolve();
    server.close(() => resolve());
  });
  server = null;
});

describe("probeSelfHostServer", () => {
  it("accepts a GAIA server with local sign-in", async () => {
    let path = "";
    const origin = await serve((req, res) => {
      path = req.url ?? "";
      json({ auth_mode: "local" })(req, res);
    });

    expect(await probeSelfHostServer(origin, netLikeFetch)).toEqual({
      ok: true,
      origin,
    });
    expect(path).toBe("/api/v1/setup/status");
  });

  it("returns the origin the server redirected to", async () => {
    const target = await serve(json({ auth_mode: "local" }));
    const targetServer = server;
    const redirector = createServer((_req, res) => {
      res.writeHead(308, { location: `${target}/api/v1/setup/status` });
      res.end();
    });
    await new Promise<void>((resolve) =>
      redirector.listen(0, "127.0.0.1", resolve),
    );
    const { port } = redirector.address() as AddressInfo;

    try {
      expect(
        await probeSelfHostServer(`http://127.0.0.1:${port}`, netLikeFetch),
      ).toEqual({ ok: true, origin: target });
    } finally {
      await new Promise<void>((resolve) => redirector.close(() => resolve()));
      server = targetServer;
    }
  });

  it("rejects a server that signs in through WorkOS", async () => {
    const origin = await serve(json({ detail: "Not authenticated" }, 401));
    const result = await probeSelfHostServer(origin, netLikeFetch);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toMatch(/GAIA Cloud/);
  });

  it("rejects a server reporting workos auth", async () => {
    const origin = await serve(json({ auth_mode: "workos" }));
    expect((await probeSelfHostServer(origin, netLikeFetch)).ok).toBe(false);
  });

  it("rejects a site that is not GAIA", async () => {
    const origin = await serve((_req, res) => {
      res.writeHead(200, { "content-type": "text/html" });
      res.end("<html>hello</html>");
    });
    const result = await probeSelfHostServer(origin, netLikeFetch);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toMatch(/No GAIA server/);
  });

  it("rejects an address with nothing behind /api/v1", async () => {
    const origin = await serve(json({ detail: "Not Found" }, 404));
    const result = await probeSelfHostServer(origin, netLikeFetch);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toMatch(/No GAIA server/);
  });

  it("reports an unreachable server", async () => {
    const origin = await serve(json({}));
    await new Promise<void>((resolve) => server?.close(() => resolve()));
    server = null;
    const result = await probeSelfHostServer(origin, netLikeFetch);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toMatch(/Couldn't reach/);
  });
});
