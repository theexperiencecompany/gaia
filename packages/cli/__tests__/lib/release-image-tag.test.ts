import { describe, expect, it } from "vitest";
import { releaseImageTag } from "../../src/lib/version.js";

describe("releaseImageTag", () => {
  it("is the CLI's own release by default", () => {
    expect(releaseImageTag({}, "0.7.0-beta.4")).toBe("v0.7.0-beta.4");
  });

  it("follows GAIA_VERSION, the tag compose runs, when it names another release", () => {
    expect(
      releaseImageTag({ GAIA_VERSION: "v0.7.0-beta.3" }, "0.7.0-beta.4"),
    ).toBe("v0.7.0-beta.3");
  });

  it("ignores an empty GAIA_VERSION", () => {
    expect(releaseImageTag({ GAIA_VERSION: "" }, "0.7.0")).toBe("v0.7.0");
  });
});
