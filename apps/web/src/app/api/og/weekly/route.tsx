import type { NextRequest } from "next/server";
import { siteConfig } from "@/lib/seo";
import { createFallbackResponse } from "../lib";
import { renderWeeklyOgImage, type WeeklyOgStats } from "./weeklyOgImage";

export const runtime = "edge";

/** An invite code is a short ascii name, a dash and a suffix. */
const CODE_PATTERN = /^[a-z0-9-]{1,32}$/;
/** Far above any real week; a bigger number is a hand-edited URL, not a recap. */
const MAX_COUNT = 100_000;

function count(raw: string | null): number | null {
  if (raw === null || !/^\d+$/.test(raw)) return null;
  const value = Number(raw);
  return value <= MAX_COUNT ? value : null;
}

/** The share card's numbers arrive in the URL the card itself built; anything else renders the plain card. */
function parseStats(params: URLSearchParams): WeeklyOgStats | null {
  const code = params.get("code");
  const minutes = count(params.get("minutes"));
  const actions = count(params.get("actions"));
  const runs = count(params.get("runs"));
  if (!code || !CODE_PATTERN.test(code)) return null;
  if (minutes === null || actions === null || runs === null) return null;
  return { code, minutes, actions, runs };
}

export async function GET(request: NextRequest) {
  const stats = parseStats(request.nextUrl.searchParams);
  if (!stats) return createFallbackResponse(siteConfig.name);
  return renderWeeklyOgImage({ ...stats, baseUrl: siteConfig.url });
}
