import { LINK_ACCESS_OPTIONS } from "@/features/short-links/constants";
import { copyText } from "@/lib/clipboard";
import { toast } from "@/lib/toast";
import type { ShortLinkResponse } from "@/types/features/shortLinkTypes";

/** Copy a heygaia.link and say who can open it; a refused clipboard says so. */
export async function copyShortLink({
  url,
  access,
}: Pick<ShortLinkResponse, "url" | "access">): Promise<void> {
  try {
    await copyText(url);
  } catch {
    toast.error("Couldn't copy the link", {
      description: "Your browser blocked clipboard access.",
    });
    return;
  }
  toast.success("Link copied", {
    description: LINK_ACCESS_OPTIONS[access].copiedNote,
  });
}
