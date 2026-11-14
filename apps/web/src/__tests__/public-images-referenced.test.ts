/**
 * Every image under public/images is referenced by a tracked file. An image
 * nobody points at still ships in every build and every clone, so a removed
 * usage must take its asset with it. Integration logos are resolved through
 * the shared registry, which builds their paths at runtime. The generated
 * dimensions file lists every image on disk, so it is no reference.
 */
import { execFileSync } from "node:child_process";
import path from "node:path";
import {
  getWebIntegrationLogoPath,
  INTEGRATION_LOGO_FILES,
} from "@shared/icons";
import { describe, expect, it } from "vitest";

const REPO_ROOT = path.resolve(process.cwd(), "../..");
const PUBLIC_IMAGES_DIR = "apps/web/public/images/";
const PUBLIC_DIR = "apps/web/public";

const IMAGE_FILE = /\.(png|jpe?g|gif|webp|avif|svg|ico)$/i;
/** A public image URL as written in source, markdown, JSON or CSS. */
const IMAGE_URL = "/images/[[:alnum:]_./@%-]+";
const GIT_OUTPUT_LIMIT = 64 * 1024 * 1024;
const IMAGE_DIMENSIONS_FILE =
  "apps/web/src/lib/image-dimensions.generated.json";

function git(args: string[]): string[] {
  return execFileSync("git", args, {
    cwd: REPO_ROOT,
    encoding: "utf8",
    maxBuffer: GIT_OUTPUT_LIMIT,
  })
    .split("\n")
    .filter(Boolean);
}

/** Collect the image URLs in every tracked text file with one native git grep. */
function referencedImageUrls(): Set<string> {
  const matches = git([
    "grep",
    "--only-matching",
    "-h",
    "--no-line-number",
    "--no-column",
    "-I",
    "-E",
    IMAGE_URL,
    "--",
    ".",
    `:!${IMAGE_DIMENSIONS_FILE}`,
  ]);
  const urls = new Set(
    matches.map((url) => decodeURIComponent(url).replace(/\.+$/, "")),
  );
  for (const key of Object.keys(INTEGRATION_LOGO_FILES)) {
    const logo = getWebIntegrationLogoPath(key);
    if (logo) urls.add(logo);
  }
  return urls;
}

describe("public/images", () => {
  it("contains only images some tracked file references", () => {
    const referenced = referencedImageUrls();
    const unreferenced = git(["ls-files", "--", PUBLIC_IMAGES_DIR])
      .filter((f) => IMAGE_FILE.test(f))
      .map((f) => f.slice(PUBLIC_DIR.length))
      .filter((url) => !referenced.has(url));
    expect(unreferenced).toEqual([]);
  });
});
