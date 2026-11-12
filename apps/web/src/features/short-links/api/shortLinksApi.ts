import { API_BASE } from "@/lib/api/baseUrl";
import { api } from "@/lib/api/typed";
import type { ShortLinkTargetType } from "@/types/features/shortLinkTypes";

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

/** The owner's live heygaia.link for an artifact, or null when it isn't shared. Never mints one. */
export async function fetchShareState(
  targetType: ShortLinkTargetType,
  targetId: string,
): Promise<string | null> {
  const { url } = await api.get("/api/v1/l/state", {
    query: { target_type: targetType, target_id: targetId },
    errorMessage: "Couldn't check whether this is shared",
  });
  return url;
}

/**
 * Stop sharing an artifact: its link stops opening at once, and GAIA attaches
 * no new link to it until the owner shares it again. Resolves to whether a
 * live link was actually turned off.
 */
export async function stopSharingShortLink(
  targetType: ShortLinkTargetType,
  targetId: string,
): Promise<boolean> {
  const { revoked } = await api.post("/api/v1/l/unshare", {
    body: { target_type: targetType, target_id: targetId },
    errorMessage: "Couldn't stop sharing",
  });
  return revoked;
}

/** Tell the API this browser opened a link; it decides whether that counts. Never surfaces an error. */
export async function recordShortLinkOpen(slug: string): Promise<void> {
  await api.post("/api/v1/l/{slug}/opened", {
    path: { slug },
    silent: true,
  });
}

/** Browser URL of the raw file behind a session-artifact slug. */
export function shortLinkFileUrl(slug: string): string {
  return `${API_BASE}/l/${encodeURIComponent(slug)}/file`;
}

/** Browser URL of the PDF export of an artifact slug. */
export function shortLinkPdfDownloadUrl(slug: string): string {
  return `${API_BASE}/l/${encodeURIComponent(slug)}/pdf`;
}
