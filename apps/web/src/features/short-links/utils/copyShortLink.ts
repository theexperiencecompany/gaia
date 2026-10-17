import { toast } from "@/lib/toast";

/** Copy a heygaia.link and say who can open it; a refused clipboard says so. */
export async function copyShortLink(url: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(url);
  } catch {
    toast.error("Couldn't copy the link", {
      description: "Your browser blocked clipboard access.",
    });
    return;
  }
  toast.success("Link copied", {
    description: "Anyone with this link can view it.",
  });
}
