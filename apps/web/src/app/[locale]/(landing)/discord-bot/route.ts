import { DISCORD_CLIENT_ID } from "@shared/constants/bots";
import { discordInviteUrl } from "@shared/utils/botLinks";
import { NextResponse } from "next/server";

/** /discord-bot forwards to Discord's install screen; a route, not a page, so it answers a real 307. */
export function GET(): NextResponse {
  return NextResponse.redirect(discordInviteUrl(DISCORD_CLIENT_ID), 307);
}
