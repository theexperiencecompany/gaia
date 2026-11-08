import { SLACK_CLIENT_ID } from "@shared/constants/bots";
import { slackInstallUrl } from "@shared/utils/botLinks";
import { NextResponse } from "next/server";

/** /slack-bot forwards to Slack's install screen; a route, not a page, so it answers a real 307. */
export function GET(): NextResponse {
  return NextResponse.redirect(slackInstallUrl(SLACK_CLIENT_ID), 307);
}
