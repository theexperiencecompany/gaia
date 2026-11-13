import { type NextRequest, NextResponse } from "next/server";

// The blog write credential lives ONLY on the server. It must never carry a
// NEXT_PUBLIC_ prefix — that would inline it into the client bundle.
const BLOG_BEARER_TOKEN = process.env.BLOG_BEARER_TOKEN;
// Read the API base server-side. The value is the same origin the client used;
// reading it here (not shipping the token) is what makes this safe.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

/**
 * Server-side proxy for creating blog posts.
 *
 * Forwards the multipart form body to the backend `blogs` endpoint with the
 * server-only bearer token, so the write credential is never exposed to the
 * browser. The caller's session cookie is forwarded for backend auth.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!BLOG_BEARER_TOKEN) {
    return NextResponse.json(
      { error: "Blog management is not configured." },
      { status: 503 },
    );
  }

  if (!API_BASE_URL) {
    return NextResponse.json(
      { error: "API base URL is not configured." },
      { status: 500 },
    );
  }

  // CSRF: reject a cross-site form POST (foreign/absent Origin) before
  // attaching the write credential. Compare Origin's host to Host — both
  // are browser-provided and stay consistent behind a proxy/CDN.
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  let originHost: string | null = null;
  try {
    originHost = origin ? new URL(origin).host : null;
  } catch {
    originHost = null;
  }
  if (!originHost || !host || originHost !== host) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  // Require an authenticated session — unauthenticated callers carry no session
  // cookie, so reject before touching the backend or the write credential.
  const cookie = request.headers.get("cookie");
  if (!cookie) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const formData = await request.formData();

  // Build target via URL parser (keeps scheme/host/port/query intact),
  // appending `/blogs` regardless of a trailing slash — guarded since a
  // malformed API_BASE_URL would otherwise throw and crash the handler.
  let backendUrl: URL;
  try {
    backendUrl = new URL(API_BASE_URL);
  } catch {
    return NextResponse.json(
      { error: "API base URL is not configured correctly." },
      { status: 500 },
    );
  }
  backendUrl.pathname = `${backendUrl.pathname.replace(/\/+$/, "")}/blogs`;

  const backendResponse = await fetch(backendUrl, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${BLOG_BEARER_TOKEN}`,
      cookie,
    },
    body: formData,
  });

  // This handler is a proxy, not an interpreter: the backend's response is
  // relayed verbatim (status + payload) so the client sees the exact API
  // contract — including error bodies, forwarded as-is below.
  if (!backendResponse.ok) {
    const errorPayload = await readBackendPayload(backendResponse);
    return NextResponse.json(errorPayload, {
      status: backendResponse.status,
    });
  }

  const payload = await readBackendPayload(backendResponse);
  return NextResponse.json(payload, { status: backendResponse.status });
}

async function readBackendPayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return await response.json();
  }
  return await response.text();
}
