import { NextResponse } from "next/server";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

/**
 * Login-free integration-connect deep link.
 *
 * Forwards the opaque `heygaia.io/connect/<code>` to the API connect-link
 * endpoint, which consumes it and redirects into the provider's OAuth flow.
 * Server-side keeps the code out of any `Referer`; `no-store` keeps it
 * uncached; excluded from i18n middleware as a locale-invariant redirect.
 */
export async function GET(
  _request: Request,
  props: { params: Promise<{ code: string }> },
) {
  const { code } = await props.params;

  if (!API_BASE_URL) {
    return new NextResponse("Connect link is not configured", { status: 500 });
  }

  const base = API_BASE_URL.replace(/\/+$/, "");
  const target = `${base}/integrations/connect-link?code=${encodeURIComponent(code)}`;

  return NextResponse.redirect(target, {
    status: 307,
    headers: { "Cache-Control": "no-store" },
  });
}
