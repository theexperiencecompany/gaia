/** Copying a heygaia.link: a refused clipboard is reported, never a false "copied". */

import { afterEach, describe, expect, it, vi } from "vitest";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));

import { copyShortLink } from "@/features/short-links/utils/copyShortLink";

const URL = "https://heygaia.link/abcdefghijk";
const UNLISTED = { url: URL, access: "unlisted" } as const;

function stubClipboard(writeText: (text: string) => Promise<void>) {
  vi.stubGlobal("navigator", { clipboard: { writeText } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("copyShortLink", () => {
  it("copies the link and says who can open it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);

    await copyShortLink(UNLISTED);

    expect(writeText).toHaveBeenCalledWith(URL);
    expect(toast.success).toHaveBeenCalledWith("Link copied", {
      description: "Anyone with this link can view it.",
    });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("says only the listed people can open a people link", async () => {
    stubClipboard(vi.fn().mockResolvedValue(undefined));

    await copyShortLink({ url: URL, access: "people" });

    expect(toast.success).toHaveBeenCalledWith("Link copied", {
      description: "Only the people you added can view it, once signed in.",
    });
  });

  it("shows the error toast, not success, when the clipboard is refused", async () => {
    stubClipboard(vi.fn().mockRejectedValue(new DOMException("denied")));

    await expect(copyShortLink(UNLISTED)).resolves.toBeUndefined();

    expect(toast.error).toHaveBeenCalledWith("Couldn't copy the link", {
      description: "Your browser blocked clipboard access.",
    });
    expect(toast.success).not.toHaveBeenCalled();
  });
});
