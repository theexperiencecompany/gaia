import { NextResponse } from "next/server";

import { slackInstallUrl } from "@/features/bots/installLinks";

/** /slack-bot forwards to Slack's install screen; a route, not a page, so it answers a real 307. */
export function GET(): NextResponse {
  return NextResponse.redirect(slackInstallUrl(), 307);
}
