import { afterEach, describe, expect, it, vi } from "vitest";
import {
  imageLayerSizes,
  parseImageRef,
  tokenUrl,
} from "../../src/lib/pull-size.js";

afterEach(() => vi.unstubAllGlobals());

describe("parseImageRef", () => {
  it("reads a Docker Hub official image as library/<name> on its API host", () => {
    expect(parseImageRef("mongo:8")).toEqual({
      host: "registry-1.docker.io",
      repository: "library/mongo",
      reference: "8",
    });
  });

  it("reads a Docker Hub user image and a GHCR image", () => {
    expect(parseImageRef("chromadb/chroma:1.5.1")).toMatchObject({
      host: "registry-1.docker.io",
      repository: "chromadb/chroma",
    });
    expect(
      parseImageRef("ghcr.io/theexperiencecompany/gaia:v0.7.0-beta.3"),
    ).toEqual({
      host: "ghcr.io",
      repository: "theexperiencecompany/gaia",
      reference: "v0.7.0-beta.3",
    });
  });

  it("defaults the tag to latest", () => {
    expect(parseImageRef("redis").reference).toBe("latest");
  });
});

describe("tokenUrl", () => {
  it("builds the token request a registry's challenge names", () => {
    expect(
      tokenUrl(
        'Bearer realm="https://auth.docker.io/token",service="registry.docker.io",scope="repository:library/mongo:pull"',
      ),
    ).toBe(
      "https://auth.docker.io/token?service=registry.docker.io&scope=repository%3Alibrary%2Fmongo%3Apull",
    );
  });

  it("names nothing for a challenge that is not a bearer token", () => {
    expect(tokenUrl('Basic realm="x"')).toBeNull();
  });
});

describe("imageLayerSizes", () => {
  it("follows the challenge and the index to this CPU's layers, by Docker's short ids", async () => {
    const asked: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        asked.push(url);
        const auth = (init?.headers as Record<string, string> | undefined)
          ?.Authorization;
        if (url.startsWith("https://auth.example/token")) {
          return Response.json({ token: "t0k" });
        }
        if (!auth) {
          return new Response("", {
            status: 401,
            headers: {
              "www-authenticate":
                'Bearer realm="https://auth.example/token",service="reg",scope="repository:library/mongo:pull"',
            },
          });
        }
        if (url.endsWith("/manifests/8")) {
          return Response.json({
            manifests: [
              {
                digest: "sha256:amd",
                platform: { os: "linux", architecture: "amd64" },
              },
              {
                digest: "sha256:arm",
                platform: { os: "linux", architecture: "arm64" },
              },
            ],
          });
        }
        if (url.endsWith("/manifests/sha256:arm")) {
          return Response.json({
            layers: [
              { digest: `sha256:${"a".repeat(64)}`, size: 1000 },
              { digest: `sha256:${"b".repeat(64)}`, size: 250 },
            ],
          });
        }
        return new Response("", { status: 404 });
      }),
    );

    const sizes = await imageLayerSizes("mongo:8", "arm64");

    expect([...sizes]).toEqual([
      ["aaaaaaaaaaaa", 1000],
      ["bbbbbbbbbbbb", 250],
    ]);
    expect(asked.some((url) => url.endsWith("/manifests/sha256:amd"))).toBe(
      false,
    );
  });
});
