import { afterEach, describe, expect, it, vi } from "vitest";
import {
  findReleaseImageGap,
  publishedArchitectures,
} from "../../src/lib/image-availability.js";
import { isNewerRelease } from "../../src/lib/update-check.js";

/** A GHCR double: a token, then the manifest (or 404) per repo:tag, and config blobs. */
function stubRegistry(
  manifests: Record<string, unknown>,
  blobs: Record<string, unknown> = {},
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("/token?")) {
        return { ok: true, status: 200, json: async () => ({ token: "t" }) };
      }
      const manifest =
        /\/v2\/theexperiencecompany\/([\w-]+)\/manifests\/(.+)$/.exec(url);
      if (manifest) {
        const body = manifests[`${manifest[1]}:${manifest[2]}`];
        return body
          ? { ok: true, status: 200, json: async () => body }
          : { ok: false, status: 404, json: async () => ({}) };
      }
      const blob = /\/blobs\/(.+)$/.exec(url);
      return {
        ok: true,
        status: 200,
        json: async () => blobs[blob?.[1] ?? ""],
      };
    }),
  );
}

const index = (...archs: string[]) => ({
  manifests: [...archs, "unknown"].map((architecture) => ({
    platform: { architecture, os: "linux" },
  })),
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("publishedArchitectures", () => {
  it("reads a multi-arch index, ignoring attestation entries", async () => {
    stubRegistry({ "gaia-web:latest": index("amd64", "arm64") });
    expect(await publishedArchitectures("gaia-web", "latest")).toEqual([
      "amd64",
      "arm64",
    ]);
  });

  it("reads a single-platform image's CPU from its config", async () => {
    stubRegistry(
      { "gaia:v1": { config: { digest: "sha256:c" } } },
      { "sha256:c": { architecture: "amd64" } },
    );
    expect(await publishedArchitectures("gaia", "v1")).toEqual(["amd64"]);
  });

  it("is empty for a tag that does not exist", async () => {
    stubRegistry({});
    expect(await publishedArchitectures("gaia", "v0.6.0")).toEqual([]);
  });
});

describe("findReleaseImageGap", () => {
  it("names the image with no build for this CPU", async () => {
    stubRegistry({
      "gaia:latest": index("amd64", "arm64"),
      "gaia-web:latest": index("amd64"),
    });
    expect(await findReleaseImageGap("latest", [], "arm64")).toEqual({
      kind: "wrong-cpu",
      image: "gaia-web:latest",
      arch: "arm64",
    });
  });

  it("names an unpublished release", async () => {
    stubRegistry({});
    expect(await findReleaseImageGap("v0.6.0", [], "arm64")).toEqual({
      kind: "not-published",
      image: "gaia:v0.6.0",
    });
  });

  it("checks enabled bots too, and passes a complete release", async () => {
    stubRegistry({
      "gaia:v1": index("arm64"),
      "gaia-web:v1": index("arm64"),
      "gaia-bot-slack:v1": index("arm64"),
    });
    expect(await findReleaseImageGap("v1", ["slack"], "arm64")).toBeNull();
    expect(await findReleaseImageGap("v1", ["discord"], "arm64")).toEqual({
      kind: "not-published",
      image: "gaia-bot-discord:v1",
    });
  });
});

describe("isNewerRelease", () => {
  it("compares releases and never calls a development build older or newer", () => {
    expect(isNewerRelease("v0.7.0", "v0.6.0")).toBe(true);
    expect(isNewerRelease("v0.6.0", "v0.6.0")).toBe(false);
    expect(isNewerRelease("v0.6.0", "latest")).toBe(false);
    expect(isNewerRelease("v0.7.0-beta.1", "v0.6.0")).toBe(true);
  });
});
