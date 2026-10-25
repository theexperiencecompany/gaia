import * as http from "node:http";
import type { AddressInfo } from "node:net";
import { afterEach, describe, expect, it } from "vitest";
import { fetchDependencyReadiness } from "../../src/lib/dependency-readiness.js";

let server: http.Server | undefined;

/** A local API that answers /health/ready with this status and body. */
async function serveReadiness(status: number, body: unknown): Promise<string> {
  server = http.createServer((req, res) => {
    if (req.url !== "/health/ready") {
      res.writeHead(404).end();
      return;
    }
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  });
  await new Promise<void>((resolve) => server?.listen(0, "127.0.0.1", resolve));
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}

afterEach(async () => {
  await new Promise<void>((resolve) => server?.close(() => resolve()));
  server = undefined;
});

describe("fetchDependencyReadiness", () => {
  it("reports each dependency of a 503 and names the fix for the failed one", async () => {
    const origin = await serveReadiness(503, {
      status: "not_ready",
      dependencies: [
        { name: "mongodb", ok: true, latency_ms: 1.2, error_type: null },
        {
          name: "postgres",
          ok: false,
          latency_ms: 2000,
          error_type: "TimeoutError",
        },
      ],
    });

    const readiness = await fetchDependencyReadiness(origin, "gaia-selfhost");

    expect(readiness.reachable).toBe(true);
    if (!readiness.reachable) return;
    expect(readiness.ready).toBe(false);
    const [mongo, postgres] = readiness.dependencies;
    expect(mongo?.fix).toBeUndefined();
    expect(postgres?.error_type).toBe("TimeoutError");
    expect(postgres?.fix).toContain(
      "docker compose -p gaia-selfhost logs postgres",
    );
  });

  it("is ready when every dependency answered", async () => {
    const origin = await serveReadiness(200, {
      status: "ready",
      dependencies: [
        { name: "redis", ok: true, latency_ms: 0.4, error_type: null },
      ],
    });

    const readiness = await fetchDependencyReadiness(origin, "gaia-dev");

    expect(readiness).toEqual({
      reachable: true,
      ready: true,
      dependencies: [
        { name: "redis", ok: true, latency_ms: 0.4, error_type: null },
      ],
    });
  });

  it("calls an API without the endpoint unreachable instead of ready", async () => {
    const origin = await serveReadiness(404, { message: "Not Found" });

    const readiness = await fetchDependencyReadiness(origin, "gaia-selfhost");

    expect(readiness).toEqual({
      reachable: false,
      detail: `HTTP 404 from ${origin}/health/ready`,
    });
  });
});
