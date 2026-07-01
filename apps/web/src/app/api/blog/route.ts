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

  // Require an authenticated session — unauthenticated callers carry no session
  // cookie, so reject before touching the backend or the write credential.
  const cookie = request.headers.get("cookie");
  if (!cookie) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const formData = await request.formData();

  const backendResponse = await fetch(`${API_BASE_URL}blogs`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${BLOG_BEARER_TOKEN}`,
      cookie,
    },
    body: formData,
  });

  const contentType = backendResponse.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await backendResponse.json()
    : await backendResponse.text();

  return NextResponse.json(payload, { status: backendResponse.status });
}
