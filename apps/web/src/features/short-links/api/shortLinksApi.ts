import { api } from "@/lib/api/typed";
import type {
  LinkSettings,
  LinkSettingsUpdate,
  ShortLinkResponse,
  ShortLinkTargetType,
} from "@/types/features/shortLinkTypes";

/**
 * Share an artifact the signed-in user owns: its heygaia.link, minted on first
 * use with the given settings. While a link is live the same link comes back
 * unchanged, settings ignored; sharing again after stopping mints a new one.
 */
export async function createShortLink(
  targetType: ShortLinkTargetType,
  targetId: string,
  settings?: LinkSettings,
): Promise<ShortLinkResponse> {
  return api.post("/api/v1/l", {
    body: { target_type: targetType, target_id: targetId, settings },
    errorMessage: "Couldn't create a link",
  });
}

/** The owner's live heygaia.link for an artifact, or null when it isn't shared. Never mints one. */
export async function fetchShareState(
  targetType: ShortLinkTargetType,
  targetId: string,
): Promise<ShortLinkResponse | null> {
  const { link } = await api.get("/api/v1/l/state", {
    query: { target_type: targetType, target_id: targetId },
    errorMessage: "Couldn't check whether this is shared",
  });
  return link;
}

/** Change who a live link opens for, or when it expires; an omitted field keeps its value. */
export async function updateLinkSettings(
  slug: string,
  change: LinkSettingsUpdate,
): Promise<ShortLinkResponse> {
  return api.patch("/api/v1/l/{slug}", {
    path: { slug },
    body: change,
    errorMessage: "Couldn't save the share settings",
  });
}

/** Replace a live link with a new URL carrying the same settings; the old URL stops opening. */
export async function rotateLink(slug: string): Promise<ShortLinkResponse> {
  return api.post("/api/v1/l/{slug}/rotate", {
    path: { slug },
    errorMessage: "Couldn't get a new link",
  });
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
