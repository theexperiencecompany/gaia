import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import type { AddressInfo } from "node:net";

export interface TestServer {
  /** http://localhost:<port>, the shape the CLI's own origins take. */
  url: string;
  port: number;
  /** Request paths, in the order they arrived. */
  requests: string[];
  /** Each request's headers, so an Authorization round trip can be asserted. */
  headers: IncomingMessage["headers"][];
  close(): Promise<void>;
}

export type TestServerHandler = (
  req: IncomingMessage,
  res: ServerResponse,
) => void;

/**
 * A real HTTP server on a free loopback port. Probes and API calls run for
 * real against it — a stubbed fetch proves the stub, not the client.
 */
export async function startTestServer(
  handler: TestServerHandler,
): Promise<TestServer> {
  const requests: string[] = [];
  const headers: IncomingMessage["headers"][] = [];
  const server = createServer((req, res) => {
    requests.push(req.url ?? "");
    headers.push(req.headers);
    handler(req, res);
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    // No host: binds both loopback families, so "localhost" resolves either way.
    server.listen(0, resolve);
  });

  const { port } = server.address() as AddressInfo;
  return {
    url: `http://localhost:${port}`,
    port,
    requests,
    headers,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      }),
  };
}

/** A port nothing listens on: bind, read the number, let it go. */
export async function closedPort(): Promise<number> {
  const server = await startTestServer(() => {
    // The binding is all this needs; nothing ever reaches it.
  });
  const { port } = server;
  await server.close();
  return port;
}

export function sendJson(
  res: ServerResponse,
  body: unknown,
  status = 200,
): void {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

/** A body with the shape a web server or proxy writes, not the API. */
export function sendHtml(res: ServerResponse, status = 404): void {
  res.writeHead(status, { "content-type": "text/html; charset=utf-8" });
  res.end("<!DOCTYPE html><title>Not Found</title>");
}
