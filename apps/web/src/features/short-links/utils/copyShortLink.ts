import { toast } from "@/lib/toast";

/** Copy a heygaia.link and say who can open it. */
export async function copyShortLink(url: string): Promise<void> {
  await navigator.clipboard.writeText(url);
  toast.success("Link copied", {
    description: "Anyone with this link can view it.",
  });
}

/** `https://heygaia.link/abc` → `heygaia.link/abc`, the form shown in the UI. */
export function displayShortLink(url: string): string {
  return url.replace(/^https?:\/\//, "");
}
