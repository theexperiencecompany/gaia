import { describe, expect, it } from "vitest";
import { isPrivateBlobUrl } from "@/lib/privateBlob";

describe("isPrivateBlobUrl", () => {
  it("flags the self-host blob route so next/image never optimizes it", () => {
    expect(isPrivateBlobUrl("/api/v1/blobs/u1/file_1_a.png")).toBe(true);
  });

  it.each([
    "https://res.cloudinary.com/demo/image/upload/a.png",
    "/images/avatars/default.webp",
    "blob:http://localhost:3000/abc",
    "",
    undefined,
    null,
  ])("leaves %s to the optimizer", (src) => {
    expect(isPrivateBlobUrl(src)).toBe(false);
  });
});
