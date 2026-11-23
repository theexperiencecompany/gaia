import { BOT_URLS } from "@shared/constants/bots";
import { NextResponse } from "next/server";

/** /slack-bot forwards to Slack's install screen; a route, not a page, so it answers a real 307. */
export function GET(): NextResponse {
  return NextResponse.redirect(BOT_URLS.slackInstall, 307);
}
