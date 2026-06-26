import { NextResponse } from "next/server";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

/**
 * Login-free integration-connect deep link.
 *
 * Bots hand the user a short `heygaia.io/connect/<code>` URL. This server-side
 * redirect forwards the opaque, single-use code to the API connect-link
 * endpoint, which consumes it and bounces the browser straight into the
 * provider's OAuth flow. Doing it server-side (not a client page) keeps the
 * code out of any document `Referer`, and `no-store` keeps it uncached.
 *
 * Excluded from the i18n middleware (see `middleware.ts`) so it isn't rewritten
 * into the `[locale]` tree — this is a locale-invariant redirect, not a page.
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
