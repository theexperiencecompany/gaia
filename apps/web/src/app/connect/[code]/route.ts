import { NextResponse } from "next/server";

import {
  CONNECT_LINK_COOKIE,
  CONNECT_LINK_COOKIE_MAX_AGE_SECONDS,
  CONNECT_LINK_PATH,
} from "@/features/integrations/constants/connect";

/**
 * Entry point for the single-use connect links bots send. Moves the code into
 * an HttpOnly cookie and redirects to /connect, so the page that loads
 * analytics never has it in its URL. Spends nothing: link-preview crawlers GET
 * every link in a chat, so the code is only spent by the Continue form's POST.
 */
export async function GET(
  request: Request,
  props: { params: Promise<{ code: string }> },
) {
  const { code } = await props.params;
  const target = new URL(CONNECT_LINK_PATH, request.url);

  const response = NextResponse.redirect(target, 303);
  response.headers.set("Cache-Control", "no-store");
  response.cookies.set(CONNECT_LINK_COOKIE, code, {
    httpOnly: true,
    secure: target.protocol === "https:",
    sameSite: "lax",
    path: CONNECT_LINK_PATH,
    maxAge: CONNECT_LINK_COOKIE_MAX_AGE_SECONDS,
  });
  return response;
}
