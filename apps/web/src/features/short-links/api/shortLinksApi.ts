import { api } from "@/lib/api/typed";
import type { ShortLinkTargetType } from "@/types/features/shortLinkTypes";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(
  /\/$/,
  "",
);

/**
 * Share an artifact the signed-in user owns: its heygaia.link, minted on first
 * use. The same target returns the same link until sharing is stopped; sharing
 * again after that turns it back on with a new link.
 */
export async function createShortLink(
  targetType: ShortLinkTargetType,
  targetId: string,
): Promise<string> {
  const { url } = await api.post("/api/v1/l", {
    body: { target_type: targetType, target_id: targetId },
    errorMessage: "Couldn't create a link",
  });
  return url;
}

/**
 * Stop sharing an artifact: its link stops opening at once, and GAIA attaches
 * no new link to it until the owner shares it again.
 */
export async function stopSharingShortLink(
  targetType: ShortLinkTargetType,
  targetId: string,
): Promise<void> {
  await api.post("/api/v1/l/unshare", {
    body: { target_type: targetType, target_id: targetId },
    errorMessage: "Couldn't stop sharing",
  });
}

/** Browser URL of the raw file behind a session-artifact slug. */
export function shortLinkFileUrl(slug: string): string {
  return `${API_BASE}/l/${encodeURIComponent(slug)}/file`;
}
