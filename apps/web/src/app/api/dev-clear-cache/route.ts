import { NextResponse } from "next/server";

/**
 * Dev-only escape hatch to evict the long-cached _next/static chunks that
 * an earlier next.config.mjs left in Chrome's HTTP cache (it claimed
 * immutable + max-age=year, so without busting the chunk URL the browser
 * never re-validates). Returns `Clear-Site-Data: "cache"` which tells
 * Chrome to drop the origin's HTTP cache immediately.
 *
 * Refuses in production. Only meant to be hit once per browser to recover
 * after pulling the immutable-Cache-Control fix.
 */
export async function GET(): Promise<NextResponse> {
  if (process.env.NODE_ENV === "production") {
    return new NextResponse("forbidden", { status: 403 });
  }
  return new NextResponse("cleared", {
    status: 200,
    headers: {
      "Clear-Site-Data": '"cache"',
      "Cache-Control": "no-store",
    },
  });
}
