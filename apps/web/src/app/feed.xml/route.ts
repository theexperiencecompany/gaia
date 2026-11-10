import { NextResponse } from "next/server";

/** The feed moved to /feed so sitemap scanners stop parsing it as a sitemap; old subscribers keep working. */
export function GET(request: Request): NextResponse {
  return NextResponse.redirect(new URL("/feed", request.url), 301);
}
