import { apiService } from "@/lib/api/service";
import type { ShortLinkTargetType } from "@/types/features/shortLinkTypes";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(
  /\/$/,
  "",
);

/**
 * Mint (or fetch) the heygaia.link for an artifact the signed-in user owns.
 * Idempotent server-side: the same target always returns the same link.
 */
export async function createShortLink(
  targetType: ShortLinkTargetType,
  targetId: string,
): Promise<string> {
  const { url } = await apiService.post<{ url: string }>(
    "/l",
    { target_type: targetType, target_id: targetId },
    { errorMessage: "Couldn't create a link" },
  );
  return url;
}

/** Browser URL of the raw file behind a session-artifact slug. */
export function shortLinkFileUrl(slug: string): string {
  return `${API_BASE}/l/${encodeURIComponent(slug)}/file`;
}
