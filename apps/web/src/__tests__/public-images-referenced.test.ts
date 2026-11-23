/**
 * Every image under public/images is referenced by a tracked file. An image
 * nobody points at still ships in every build and every clone, so a removed
 * usage must take its asset with it. Integration logos are resolved through
 * the shared registry, which builds their paths at runtime. A template such as
 * `/images/x/${name}.webp` references the files it can name: one segment in that
 * directory with that extension. The generated dimensions file lists every image
 * on disk, so it is no reference.
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
/** A public image path a template literal builds from one placeholder. */
const IMAGE_TEMPLATE =
  "/images/[[:alnum:]_./@%-]*\\$\\{[^}]+\\}[[:alnum:]_.-]*";
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

/** Run one native git grep over every tracked text file. */
function grepTracked(pattern: string): string[] {
  return git([
    "grep",
    "--only-matching",
    "-h",
    "--no-line-number",
    "--no-column",
    "-I",
    "-E",
    pattern,
    "--",
    ".",
    `:!${IMAGE_DIMENSIONS_FILE}`,
  ]);
}

const escapeRegExp = (text: string) =>
  text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** What each templated image path can name; a template with no image extension names nothing. */
function referencedImagePatterns(): RegExp[] {
  return grepTracked(IMAGE_TEMPLATE).flatMap((template) => {
    const [prefix, suffix] = template.split(/\$\{[^}]+\}/);
    if (!IMAGE_FILE.test(suffix)) return [];
    return [
      new RegExp(`^${escapeRegExp(prefix)}[^/]+${escapeRegExp(suffix)}$`),
    ];
  });
}

/** Collect the image URLs in every tracked text file with one native git grep. */
function referencedImageUrls(): Set<string> {
  const matches = grepTracked(IMAGE_URL);
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
    const templates = referencedImagePatterns();
    const unreferenced = git(["ls-files", "--", PUBLIC_IMAGES_DIR])
      .filter((f) => IMAGE_FILE.test(f))
      .map((f) => f.slice(PUBLIC_DIR.length))
      .filter(
        (url) =>
          !referenced.has(url) &&
          !templates.some((template) => template.test(url)),
      );
    expect(unreferenced).toEqual([]);
  });
});
