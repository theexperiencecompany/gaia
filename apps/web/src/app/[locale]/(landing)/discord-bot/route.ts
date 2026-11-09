import { NextResponse } from "next/server";

import { discordInstallUrl } from "@/features/bots/installLinks";

/** /discord-bot forwards to Discord's install screen; a route, not a page, so it answers a real 307. */
export function GET(): NextResponse {
  return NextResponse.redirect(discordInstallUrl(), 307);
}
