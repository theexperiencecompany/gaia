import { BOT_URLS } from "@shared/constants/bots";
import { NextResponse } from "next/server";

/** /discord-bot forwards to Discord's install screen; a route, not a page, so it answers a real 307. */
export function GET(): NextResponse {
  return NextResponse.redirect(BOT_URLS.discordInstall, 307);
}
