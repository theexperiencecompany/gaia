import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  bundleAssetUrls,
  checkoutOwnedFiles,
  fetchBundle,
  moveLegacySelfhostSettings,
  placeBundle,
  readBundleManifest,
  releaseSourceNotes,
  unpackBundle,
} from "../../src/lib/selfhost-bundle.js";
import {
  buildBundle as buildFixtureBundle,
  sha256 as sha,
  writeFile,
} from "./bundle-fixture.js";

let root: string;

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-bundle-"));
});

afterEach(() => {
  vi.unstubAllGlobals();
  fs.rmSync(root, { recursive: true, force: true });
});

const write = writeFile;

function buildBundle(version: string, files: Record<string, string>): Buffer {
  return buildFixtureBundle(root, version, files);
}

/** Serve one bundle and a checksum file of these contents. */
function serve(bundle: Buffer, checksum: string): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith(".sha256")) return new Response(checksum);
      return new Response(new Uint8Array(bundle), {
        headers: { "content-length": String(bundle.length) },
      });
    }),
  );
}

describe("bundleAssetUrls", () => {
  it("names the asset on the release's GitHub Release", () => {
    expect(bundleAssetUrls("v0.7.0-beta.4", {})).toEqual({
      asset: "gaia-selfhost-0.7.0-beta.4.tar.gz",
      bundle:
        "https://github.com/theexperiencecompany/gaia/releases/download/cli-v0.7.0-beta.4/gaia-selfhost-0.7.0-beta.4.tar.gz",
      checksum:
        "https://github.com/theexperiencecompany/gaia/releases/download/cli-v0.7.0-beta.4/gaia-selfhost-0.7.0-beta.4.tar.gz.sha256",
    });
  });

  it("reads the assets from GAIA_BUNDLE_BASE_URL when it is set", () => {
    expect(
      bundleAssetUrls("v0.7.0", {
        GAIA_BUNDLE_BASE_URL: "http://192.168.1.5:8790/",
      }).bundle,
    ).toBe("http://192.168.1.5:8790/gaia-selfhost-0.7.0.tar.gz");
  });

  it("refuses an image tag that is not a release", () => {
    expect(() => bundleAssetUrls("latest", {})).toThrow(/not a GAIA release/);
  });
});

describe("fetchBundle", () => {
  it("returns the bundle once its checksum matches, reporting bytes of the known size", async () => {
    const bundle = buildBundle("v1.2.3", { "infra/docker/a.yml": "a" });
    serve(bundle, `${sha(bundle)}  gaia-selfhost-1.2.3.tar.gz\n`);
    const seen: { received: number; total: number | null }[] = [];

    const bytes = await fetchBundle("v1.2.3", (p) => seen.push(p));

    expect(bytes.equals(bundle)).toBe(true);
    expect(seen.at(-1)).toEqual({
      received: bundle.length,
      total: bundle.length,
    });
  });

  it("refuses a bundle whose bytes are not the published ones", async () => {
    const bundle = buildBundle("v1.2.3", { "infra/docker/a.yml": "a" });
    serve(bundle, `${"0".repeat(64)}  gaia-selfhost-1.2.3.tar.gz\n`);

    await expect(fetchBundle("v1.2.3", () => undefined)).rejects.toThrow(
      /Checksum mismatch for gaia-selfhost-1.2.3.tar.gz/,
    );
  });

  it("refuses a checksum file that lists a different asset", async () => {
    const bundle = buildBundle("v1.2.3", { "infra/docker/a.yml": "a" });
    serve(bundle, `${sha(bundle)}  gaia-selfhost-1.2.2.tar.gz\n`);

    await expect(fetchBundle("v1.2.3", () => undefined)).rejects.toThrow(
      /no entry for gaia-selfhost-1.2.3.tar.gz/,
    );
  });

  it("says the release has no setup files when they were never published", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("Not Found", { status: 404 })),
    );

    await expect(fetchBundle("v1.2.3", () => undefined)).rejects.toThrow(
      /GAIA v1.2.3 has no published setup files/,
    );
  });
});

describe("unpackBundle", () => {
  it("unpacks the files the manifest lists", async () => {
    const bundle = buildBundle("v1.2.3", {
      "infra/docker/docker-compose.selfhost.yml": "services: {}",
    });
    const staging = path.join(root, "staging");

    const manifest = await unpackBundle(bundle, staging, "v1.2.3");

    expect(manifest.version).toBe("v1.2.3");
    expect(
      fs.readFileSync(
        path.join(staging, "infra/docker/docker-compose.selfhost.yml"),
        "utf-8",
      ),
    ).toBe("services: {}");
  });

  it("refuses a bundle built for another release", async () => {
    const bundle = buildBundle("v1.2.2", { "infra/docker/a.yml": "a" });

    await expect(
      unpackBundle(bundle, path.join(root, "staging"), "v1.2.3"),
    ).rejects.toThrow(/are for GAIA v1.2.2, not v1.2.3/);
  });
});

describe("placeBundle", () => {
  it("swaps in the new files and keeps the settings and data around them", async () => {
    const install = path.join(root, "gaia");
    await placeBundle(
      await unpackBundle(
        buildBundle("v1.0.0", {
          "infra/docker/docker-compose.selfhost.yml": "old",
          "infra/docker/selfhost/retired.yml": "gone next release",
        }),
        path.join(root, "s1"),
        "v1.0.0",
      ),
      path.join(root, "s1"),
      install,
      [],
    );
    write(install, "apps/api/.env", "INSTANCE_SECRET=keep");
    write(install, "infra/docker/.env", "GAIA_VERSION=v1.0.0");
    write(install, "backups/2026-10-01/mongo.archive", "data");

    const previous = readBundleManifest(install)?.files ?? [];
    const staging = path.join(root, "s2");
    const next = await unpackBundle(
      buildBundle("v1.1.0", {
        "infra/docker/docker-compose.selfhost.yml": "new",
      }),
      staging,
      "v1.1.0",
    );
    await placeBundle(next, staging, install, previous);

    const read = (file: string) =>
      fs.readFileSync(path.join(install, file), "utf-8");
    expect(read("infra/docker/docker-compose.selfhost.yml")).toBe("new");
    expect(read("apps/api/.env")).toBe("INSTANCE_SECRET=keep");
    expect(read("infra/docker/.env")).toBe("GAIA_VERSION=v1.0.0");
    expect(read("backups/2026-10-01/mongo.archive")).toBe("data");
    expect(
      fs.existsSync(path.join(install, "infra/docker/selfhost/retired.yml")),
    ).toBe(false);
    expect(readBundleManifest(install)?.version).toBe("v1.1.0");
    expect(fs.existsSync(staging)).toBe(false);
  });
});

describe("checkoutOwnedFiles", () => {
  function git(cwd: string, ...args: string[]): string {
    return execFileSync("git", args, { cwd, encoding: "utf-8" }).trim();
  }

  /** A clone the way `gaia up` made one: a release tag, detached. */
  function releaseCheckout(): string {
    const dir = path.join(root, "checkout");
    fs.mkdirSync(dir);
    git(dir, "init", "-q", "-b", "master");
    write(dir, "infra/docker/docker-compose.selfhost.yml", "services: {}");
    write(dir, ".gitignore", ".env\nbackups/\n");
    git(dir, "add", ".");
    git(
      dir,
      "-c",
      "user.email=t@t",
      "-c",
      "user.name=t",
      "commit",
      "-q",
      "-m",
      "release",
    );
    git(dir, "tag", "cli-v1.0.0");
    git(dir, "checkout", "-q", "--detach", "cli-v1.0.0");
    write(dir, "apps/api/.env", "INSTANCE_SECRET=keep");
    return dir;
  }

  it("lists the tracked files and the git directory, never the settings", async () => {
    const dir = releaseCheckout();

    const owned = await checkoutOwnedFiles(dir);

    expect(owned.sort()).toEqual(
      [".git", ".gitignore", "infra/docker/docker-compose.selfhost.yml"].sort(),
    );
  });

  it("refuses a checkout with local changes to its files", async () => {
    const dir = releaseCheckout();
    write(dir, "infra/docker/docker-compose.selfhost.yml", "edited");

    await expect(checkoutOwnedFiles(dir)).rejects.toThrow(
      /infra\/docker\/docker-compose.selfhost.yml/,
    );
  });

  it("refuses a source checkout on a branch, pointing at --git", async () => {
    const dir = releaseCheckout();
    git(dir, "checkout", "-q", "master");

    await expect(checkoutOwnedFiles(dir)).rejects.toThrow(
      /on the branch master.*gaia update --git/s,
    );
  });
});

describe("releaseSourceNotes", () => {
  it("says nothing for a normal run", () => {
    expect(releaseSourceNotes({}, "0.7.0")).toEqual([]);
  });

  it("names each override of where the release comes from", () => {
    expect(
      releaseSourceNotes(
        {
          GAIA_VERSION: "v0.7.0-beta.3",
          GAIA_BUNDLE_BASE_URL: "http://host.orb.internal:8790",
        },
        "0.7.0-beta.4",
      ),
    ).toEqual([
      "Installing GAIA v0.7.0-beta.3's images, not v0.7.0-beta.4's (GAIA_VERSION)",
      "Setup files from http://host.orb.internal:8790 (GAIA_BUNDLE_BASE_URL)",
    ]);
  });
});

describe("moveLegacySelfhostSettings", () => {
  let checkout: string;

  beforeEach(() => {
    checkout = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-settings-move-"));
    for (const [file, contents] of Object.entries({
      "packages/cli/selfhost/docker-compose.selfhost.yml": "",
      "infra/docker/docker-compose.yml": "",
      "infra/docker/.env": "POSTGRES_HOST_PORT=5433\n",
    })) {
      fs.mkdirSync(path.dirname(path.join(checkout, file)), {
        recursive: true,
      });
      fs.writeFileSync(path.join(checkout, file), contents);
    }
  });

  afterEach(() => fs.rmSync(checkout, { recursive: true, force: true }));

  it("carries a self-host install's settings into the moved folder", async () => {
    await moveLegacySelfhostSettings(checkout, "selfhost");
    expect(
      fs.readFileSync(
        path.join(checkout, "packages/cli/selfhost/.env"),
        "utf-8",
      ),
    ).toBe("POSTGRES_HOST_PORT=5433\n");
    expect(fs.existsSync(path.join(checkout, "infra/docker/.env"))).toBe(false);
  });

  it("leaves a developer checkout's settings beside the developer stack", async () => {
    await moveLegacySelfhostSettings(checkout, "developer");
    expect(fs.existsSync(path.join(checkout, "infra/docker/.env"))).toBe(true);
    expect(
      fs.existsSync(path.join(checkout, "packages/cli/selfhost/.env")),
    ).toBe(false);
  });
});
