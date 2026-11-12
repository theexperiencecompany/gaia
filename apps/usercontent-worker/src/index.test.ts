import { afterEach, describe, expect, it, vi } from "vitest";
import worker, { type Env } from "./index.js";

const CONTENT_ID = "abcdefghijklmnopqrstuvwxyz";
const HOST = `${CONTENT_ID}.u.heygaia.link`;
const ENV: Env = {
  API_ORIGIN: "https://api.example.test",
  INTERNAL_API_TOKEN: "internal-token",
};

function upstreamReturning(response: Response) {
  const fetchMock = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) => response,
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function forwarded(fetchMock: ReturnType<typeof upstreamReturning>): {
  url: string;
  init: RequestInit;
  headers: Headers;
} {
  expect(fetchMock).toHaveBeenCalledOnce();
  const [input, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return { url: String(input), init, headers: new Headers(init.headers) };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("host parsing", () => {
  it.each([
    "u.heygaia.link",
    `${CONTENT_ID}.heygaia.link`,
    `abcdefghijklmnopqrstuvwxy0.u.heygaia.link`,
    `abcdefghijklmnopqrstuvwxy-.u.heygaia.link`,
    `${CONTENT_ID.slice(1)}.u.heygaia.link`,
    `${CONTENT_ID}a.u.heygaia.link`,
    `abcdefghijklmnopqrstuvwxy1.u.heygaia.link`,
    `x.${CONTENT_ID}.u.heygaia.link`,
    `${CONTENT_ID}.u.heygaia.link.evil.test`,
  ])("refuses %s with 404 and never calls the API", async (host) => {
    const fetchMock = upstreamReturning(new Response("leak"));
    const response = await worker.fetch(
      new Request(`https://${host}/?t=x`),
      ENV,
    );
    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("path mapping", () => {
  it("maps the root to the snapshot route with the query intact", async () => {
    const fetchMock = upstreamReturning(new Response("bytes"));
    await worker.fetch(new Request(`https://${HOST}/?t=tok%2B1&x=2`), ENV);
    expect(forwarded(fetchMock).url).toBe(
      `https://api.example.test/api/v1/usercontent/${CONTENT_ID}?t=tok%2B1&x=2`,
    );
  });

  it("maps /thumb.jpg to the thumbnail route", async () => {
    const fetchMock = upstreamReturning(new Response("jpg"));
    await worker.fetch(new Request(`https://${HOST}/thumb.jpg`), ENV);
    expect(forwarded(fetchMock).url).toBe(
      `https://api.example.test/api/v1/usercontent/${CONTENT_ID}/thumb.jpg`,
    );
  });

  it.each(["/thumb.jpg/", "/other", "/../users/me", "/api/v1/users"])(
    "refuses %s with 404",
    async (pathname) => {
      const fetchMock = upstreamReturning(new Response("leak"));
      const response = await worker.fetch(
        new Request(`https://${HOST}${pathname}`),
        ENV,
      );
      expect(response.status).toBe(404);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("forwards HEAD as HEAD", async () => {
    const fetchMock = upstreamReturning(new Response(null));
    await worker.fetch(
      new Request(`https://${HOST}/`, { method: "HEAD" }),
      ENV,
    );
    expect(forwarded(fetchMock).init.method).toBe("HEAD");
  });

  it.each(["POST", "PUT", "DELETE", "OPTIONS"])(
    "refuses %s with 405 naming GET and HEAD",
    async (method) => {
      const fetchMock = upstreamReturning(new Response("leak"));
      const response = await worker.fetch(
        new Request(`https://${HOST}/`, { method }),
        ENV,
      );
      expect(response.status).toBe(405);
      expect(response.headers.get("Allow")).toBe("GET, HEAD");
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );
});

describe("request headers", () => {
  it("drops credentials and every header outside the allowlist", async () => {
    const fetchMock = upstreamReturning(new Response("bytes"));
    await worker.fetch(
      new Request(`https://${HOST}/?t=x`, {
        headers: {
          Cookie: "session=secret",
          Authorization: "Bearer secret",
          "X-Gaia-Internal": "forged",
          "X-Gaia-Viewer-IP": "6.6.6.6",
          "X-Gaia-Content-Host": "api.heygaia.io",
          Referer: "https://heygaia.io/l/abc",
        },
      }),
      ENV,
    );
    const { headers } = forwarded(fetchMock);
    expect(headers.get("Cookie")).toBeNull();
    expect(headers.get("Authorization")).toBeNull();
    expect(headers.get("Referer")).toBeNull();
    expect(headers.get("X-Gaia-Internal")).toBe("internal-token");
    expect(headers.get("X-Gaia-Content-Host")).toBe(HOST);
    // No CF-Connecting-IP: the forged viewer IP must not pass through either.
    expect(headers.get("X-Gaia-Viewer-IP")).toBeNull();
  });

  it("forwards the fetch destination, range and validator, the host and the viewer IP", async () => {
    const fetchMock = upstreamReturning(new Response("bytes"));
    await worker.fetch(
      new Request(`https://${HOST}/?t=x`, {
        headers: {
          "Sec-Fetch-Dest": "iframe",
          Range: "bytes=0-99",
          "If-None-Match": '"etag-1"',
          "CF-Connecting-IP": "203.0.113.7",
        },
      }),
      ENV,
    );
    const { headers, init } = forwarded(fetchMock);
    expect(headers.get("Sec-Fetch-Dest")).toBe("iframe");
    expect(headers.get("Range")).toBe("bytes=0-99");
    expect(headers.get("If-None-Match")).toBe('"etag-1"');
    expect(headers.get("X-Gaia-Viewer-IP")).toBe("203.0.113.7");
    expect(headers.get("X-Gaia-Content-Host")).toBe(HOST);
    expect(init.redirect).toBe("manual");
  });
});

describe("response", () => {
  it("strips every Set-Cookie and keeps the status, body and other headers", async () => {
    const upstream = new Response("partial", {
      status: 206,
      headers: [
        ["Content-Type", "text/plain; charset=utf-8"],
        ["Content-Range", "bytes 0-6/100"],
        ["Content-Security-Policy", "default-src 'none'; sandbox"],
        ["Set-Cookie", "a=1; Path=/"],
        ["Set-Cookie", "b=2; Path=/"],
      ],
    });
    upstreamReturning(upstream);
    const response = await worker.fetch(
      new Request(`https://${HOST}/?t=x`),
      ENV,
    );
    expect(response.status).toBe(206);
    expect(response.headers.get("Set-Cookie")).toBeNull();
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(response.headers.get("Content-Range")).toBe("bytes 0-6/100");
    expect(response.headers.get("Content-Security-Policy")).toBe(
      "default-src 'none'; sandbox",
    );
    expect(await response.text()).toBe("partial");
  });

  it("passes the API's 302 back to the browser instead of following it", async () => {
    upstreamReturning(
      new Response(null, {
        status: 302,
        headers: {
          Location: "https://heygaia.link/abc",
          "Set-Cookie": "c=3",
        },
      }),
    );
    const response = await worker.fetch(
      new Request(`https://${HOST}/?t=stale`),
      ENV,
    );
    expect(response.status).toBe(302);
    expect(response.headers.get("Location")).toBe("https://heygaia.link/abc");
    expect(response.headers.get("Set-Cookie")).toBeNull();
  });
});
